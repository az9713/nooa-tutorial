# Visibility, `doc()`, and Context

This doc covers what the LLM actually sees on each turn: the visibility rules that decide what appears in `doc()`/`exec_globals`, the context-block system that assembles the system prompt, and the event system that provides conversation history. Tracks `src/nooa/_visible.py`, `src/nooa/agentdoc/*`, `src/nooa/context_blocks/*`, `src/nooa/runtime/context*.py`, `src/nooa/runtime/events.py`, `src/nooa/runtime/middleware.py`, `src/nooa/runtime/hooks.py`.

## The visibility rule: visible by default, hide explicitly

This is the single rule that governs everything below, stated once so it doesn't need restating per-scope: **anything you can already see in Python, the LLM can see too, unless you explicitly hide it.**

| Scope | Default | Opt-out / opt-in |
|---|---|---|
| Module level (imports, constants, functions, classes) | VISIBLE | `@hidden` (functions), `Annotated[T, hidden]` (variables), `with hidden:` (imports/unannotated names) |
| Agent public methods/fields | VISIBLE | `@hidden` |
| Agent `_private` methods/fields | HIDDEN | `@spec(hidden=False)` |
| Types used in the public API | Must be defined/imported at **module level** to appear in `exec_globals` | No automatic injection — there is no opt-in shortcut, the type has to actually be at module scope |
| `self.context` / `self.events` | HIDDEN, always present | `spec(self, "context", hidden=False)` / `spec(self, "events", hidden=False)` in subclass `__init__` |

```python
from __future__ import annotations
import json
from typing import Annotated
from nooa import Agent, hidden, spec

CATEGORIES = ["billing", "technical", "general"]   # module-level: visible by default
with hidden:
    import secrets                                  # explicitly hidden import

class SearchAgent(Agent, llm=llm):
    api_key: Annotated[str, hidden] = ""             # hidden field

    def search(self, query: str) -> list[str]:       # public method: visible
        """Search the index for the query."""
        ...

    @hidden
    def rebuild_index(self) -> None:                 # explicitly hidden public method
        ...

    @spec(hidden=False)
    def _shown_helper(self) -> str:                  # private, but opted back in
        return self._compute()
```

Why does `context`/`events` get an exception to "public = visible"? Because they're framework-installed on *every* agent, not something the author chose to add — defaulting them to hidden avoids surprising every agent with a `self.context`/`self.events` API it never asked to expose, while still making them one line away (`spec(self, "context", hidden=False)`) when an agent actually needs to manage its own context or query its own history.

`nooa.visible` is a no-op context manager kept only for backward compatibility with code written against an older API that had an explicit `with visible:` block — since everything is visible by default now, it does nothing.

## `doc()` — progressive disclosure

`doc(obj)` (`src/nooa/agentdoc/`) renders an object's type shape — fields, methods with signatures and docstrings — as text. Two call shapes matter:

- `doc(self)` — the agent's own API, filtered through the visibility rules above. This is what's registered as the protected `self` context block (`doc(type(self))`, evaluated once per class since the type shape doesn't change at runtime).
- `doc(some_object)` — lets the model discover the shape of *any* object it holds a reference to, even one typed as `Any`, at the exact moment it needs to operate on it. This is how an agent can work with data whose concrete type it's never been told about in the system prompt — the prompt stays bounded even as the domain of possible types grows (`examples/quickstart/05_progressive_disclosure.py`).

Under the hood, `Agent` implements the "agentdoc protocol" itself (`__type_info__`, `__instance_values__` on `src/nooa/agent.py`) so that class introspection filters framework internals and respects `@hidden`/`@spec(hidden=False)` — dunder and single-underscore methods are hidden by default; `@spec(hidden=False)` (or the equivalent `_agentdoc_hidden=False` marker) opts one back in.

`pformat()`/`pprint()` are the companion rendering functions for *values* (as opposed to *types*) — used for the automatically-registered `state` context block (`pformat(self, max_length=50, max_string=500, max_depth=4)`) and for CodeAct's default parameter prefill. See [`reference/configuration-reference.md`](../reference/configuration-reference.md) for the truncation knobs that bound their output.

## Context blocks

A context block is a labelled piece of text pinned into the agent's system prompt, rendered as `<name>CONTENT</name>` (with an `expr="..."` attribute when the block is dynamic). Set via the `ContextApi` (`self.context`):

```python
# Static: evaluated once, at assignment time
self.context["policy"] = "Always prefer rollback over forward-fix during incidents."

# Dynamic: a Python expression, re-evaluated every LLM turn
from nooa import Context
self.context["notes"] = Context(expr="self.render_notes()")
# equivalently:
self.context.set_dynamic("notes", "self.render_notes()")
```

Three protected blocks are registered automatically by `Agent.__init__` and can't be removed by ordinary assignment (only via the class-level `context={...: None}` override mechanism): `system_prompt` (the class docstring, resolved fresh each turn since it can reference `{self.attr}`), `self` (`doc(type(self))`, static), and `state` (`pformat(self, ...)`, dynamic — instance field values and attached skills can change between turns).

Both block types render every turn as labelled sections of the same prompt — the point of the design is that **the developer and the model manipulate the same interface**: if `self.context` is exposed to the LLM (`spec(self, "context", hidden=False)`), the model can add, update, or remove its own context blocks inside CodeAct-generated code as its understanding of the task evolves, exactly the way the developer would from orchestration code.

Context can also be scoped per-call via `@strategy(..., context={...})` or `ScopedContext` — see [`concepts/agents-and-generation-methods.md`](agents-and-generation-methods.md#strategy-decorator) for the exact mechanism, and per-class via `class MyAgent(Agent, context={...})` in `__init_subclass__`.

Rendering internals — block ordering, per-strategy overrides (`GenerationStrategy.get_block_overrides()` / `get_block_order()`), formatters, and role assignment (system vs. other) — live in `src/nooa/context_blocks/renderer.py`, `roles.py`, and `renderers/`.

## Events and `EventsApi`

Every method call, LLM round-trip, code execution, and turn boundary is recorded as an event on `self.event_manager` (`EventBase` subclasses in `src/nooa/events.py` / `src/nooa/runtime/events.py` — `Task`, `LLMOutput`, `PythonOutput`, `Error`, `BeforeTurn`/`AfterTurn`, `ExecutionSignal`, and more). This append-only log is what "event sourcing" in the framework's own description refers to, and it's what conversation history *is* — there's no separate chat-message list maintained alongside it.

`self.events` (`EventsApi`, hidden by default, opt in with `spec(self, "events", hidden=False)`) is the LLM-facing, read-only query interface over that log:

```python
events.query(limit=50)                       # most recent 50
events.query(type="Task")                    # all task events
events.query(type="PythonOutput")            # execution outputs
events.query(call_id="abc123")               # events for one call
events.query(query="error", regex=False)     # text search (or regex=True)
events.get("5")                              # by stable tag, None if missing
events["5"]                                  # by tag, KeyError if missing
"5" in events                                 # existence check
```

Tags are stable string labels (`"1"`, `"2"`, ...) assigned on insert; summarized ranges use `"1..22"` and expose `.children_tags`. `EventQuery` (`src/nooa/runtime/event_query.py`) is the filter object used both for `.query()` calls and for scoping which events feed into a prompt (e.g. `EventQuery.current_call()` to show a strategy only the current call's events, used by `ScopedContext`).

## Summarization

Long-running agents accumulate unbounded event history unless something compresses it. Two built-in summarizers (`src/nooa/agents/summarization.py`):

- **`TokenBudgetSummarizer`** — compresses older turns continuously once accumulated history crosses a token budget. `TokenBudgetSummarizer.install(agent, config=TokenBudgetConfig(max_tokens=1000))`.
- **`MethodSummarizer`** — compresses each completed method call's history instead of running against a continuous budget; better fit for agents that process discrete batches. `MethodSummarizer.install(agent)`.

Both let a conversation run indefinitely without hitting the model's context window — install once, no per-call bookkeeping.

## Middleware and hooks — intercepting execution

Two distinct mechanisms for reaching into what an agent is doing, registered on `agent.event_manager`:

- **`intercept(kind, fn)`** — wraps a *live* operation and can transform or block it. Three kinds: `"agent_call"` (wraps the entire method call, all turns), `"llm_call"` (wraps `runtime.generate()`, the LLM round-trip), `"execute_python"` (wraps `runtime.execute_code()`, sandbox execution). Each middleware is `async def(ctx, nxt) -> result`, where `ctx` is a typed context object for that kind (`AgentCallContext`, `LLMCallContext`, `ExecutePythonContext`) and `nxt` calls the rest of the chain — the standard middleware-chain pattern. Use for guardrails, request/response transforms, or hard blocking.
- **`on(event_type, fn)`** — observes a *recorded* event, fire-and-forget, after the operation has already completed (e.g. `agent.event_manager.on("message", lambda e: print(e.content))`). Use for logging, metrics, or reactive side effects that don't need to change the outcome.

`src/nooa/runtime/hooks.py` (`call_before_hook`/`call_after_hook`) is the lower-level instrumentation point strategies themselves call into around method invocations and generation sessions — the `InstrumentationHooks` protocol that tracing (see [`concepts/tracing-and-observability.md`](tracing-and-observability.md)) and middleware both hook into.

## Related

- [`concepts/agents-and-generation-methods.md`](agents-and-generation-methods.md) — how context blocks and events feed into prompt assembly during a generation call.
- [`concepts/tracing-and-observability.md`](tracing-and-observability.md) — how the same hook infrastructure produces spans.
- `skills/nooa-agentdoc/SKILL.md`, `skills/nooa-context-and-state/SKILL.md`, `skills/nooa-middleware-hooks/SKILL.md` in the repo — coding-agent-facing quick references for this same material.
