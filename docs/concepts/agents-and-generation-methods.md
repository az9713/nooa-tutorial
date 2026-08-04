# Agents and Generation Methods

This doc covers what `nooa.Agent` actually is under the hood, how a `...`-bodied method becomes LLM-driven, how the docstring becomes a prompt, and how LLM resolution cascades through a class hierarchy. Tracks `src/nooa/agent.py`, `src/nooa/metaclass.py`, `src/nooa/decorators.py`, `src/nooa/prompts.py`, `src/nooa/ellipsis_detection.py`.

## What it is

`Agent` (`src/nooa/agent.py`) is the base class every NOOA agent subclasses. It uses a custom metaclass, `AgentMeta` (`src/nooa/metaclass.py`), which — at class-definition time, before any instance exists — scans every method body for a literal ellipsis (`has_ellipsis_body()` in `src/nooa/ellipsis_detection.py`) and, for each one found, wraps the method so that calling it dispatches to a `GenerationStrategy` instead of executing a function body. Methods with real bodies pass through unmodified except for automatic tracing instrumentation (unless marked `@no_trace`).

The class docstring is treated specially: `Agent._resolve_system_prompt()` walks the MRO to find the nearest class with a docstring (Python doesn't inherit `__doc__` automatically) and uses it as the system prompt, with `{expression}` placeholders resolved the same way method docstrings are (see Templating, below).

## How it works

### Construction

`Agent.__init__` (called via `MyAgent(llm=..., truncation=..., render_config=..., context=..., event_query=..., storage=...)`) sets up, per instance:

- `self._agent_id` — a fresh UUID.
- `self._storage` — a `StorageManager` (defaults to `InMemoryStorageManager` if none passed).
- `self.event_manager` — an `EventManager` backed by `self._storage.event_backend`.
- `self._llm` — resolved via cascading resolution (see below).
- `self._truncation` — resolved via merge semantics across default → class-level → instance-level `TruncationConfig`.
- `self.render_config` — a `RenderConfig` controlling block/provider formatting.
- `self.context_manager` / `self.context` (`ContextApi`) — raw and LLM-facing context-block state. Three protected blocks are registered automatically: `system_prompt` (re-evaluates `self._resolve_system_prompt()`), `self` (`doc(type(self))`, static per-class), and `state` (`pformat(self, ...)`, re-evaluated every turn since instance field values and attached skills can change at runtime).
- `self.event_manager` / `self.events` (`EventsApi`) — raw and LLM-facing event-history state.
- `self.runtime` — an `ActorRuntime` that actually executes generation calls (locking, prompt assembly, code execution).

`self.context` and `self.events` are **always present but hidden from the LLM by default** — a subclass opts in per-instance with `spec(self, "context", hidden=False)` / `spec(self, "events", hidden=False)` inside its own `__init__`. Framework-internal attributes (`runtime`, `_storage`, `event_manager`, `context_manager`, `_llm`, `_truncation`, etc.) are permanently annotated `Annotated[T, hidden, nosnapshot]` on the class, so they never leak into `doc()` output or into snapshots regardless of subclass behavior.

### Cascading LLM resolution

`Agent._resolve_llm()` implements a four-step lookup, tried in order, first match wins:

1. **Instance-level explicit** — `MyAgent(llm=my_llm)`.
2. **Class hierarchy** — `class MyAgent(Agent, llm=class_llm)`, found via `getattr(self.__class__, "_agent_llm", None)`, which walks the MRO automatically.
3. **Runtime parent propagation** — if this agent is being constructed *inside another agent's generated code*, it inherits the parent agent's LLM via a context variable (`_parent_agent_var`).
4. **Error** — if none of the above resolve, `__init__` raises `ValueError` with all three attempts and their outcomes spelled out.

Passing `llm=None` explicitly is a hard error (`_validate_llm_param`) — it exists to distinguish "I want cascading" (omit the parameter) from "I'm trying to explicitly disable the LLM" (not a supported operation; use `INHERIT` semantics by omission instead).

This is what makes the "LLM cascading resolution" pattern from `examples/README.md` work: set a class default once, override a specific method with `@strategy(..., llm=special_llm)`, override per-instance with `MyAgent(llm=different_llm)` — no method signature or caller changes.

### Truncation and execution config resolution

Similarly merge-based, but via `TruncationConfig.merge_with()` (field-by-field, later layer's *set* fields win) rather than simple override: default `DEFAULT_TRUNCATION_CONFIG` → class-level (`class MyAgent(Agent, truncation=...)`) → instance-level (`MyAgent(truncation=...)`). `ExecutionConfig` (max agent-in-agent recursion depth, default `max_nesting_depth=10`) is class-level only, set via `class MyAgent(Agent, execution=ExecutionConfig(...))`.

### Generation method dispatch

At class-definition time, `AgentMeta` recognizes an ellipsis-bodied method and, at call time, `Agent`'s wrapping routes the call through `ActorRuntime` (`src/nooa/runtime/actor.py`), which:

1. Takes a lock scoped to the agent instance so that concurrent calls to generation methods on the *same* agent are serialized — this is the "serialized execution" half of the framework's own self-description ("event sourcing and serialized execution," per `pyproject.toml`). Nested calls (a generation method's CodeAct loop calling another generation method on `self`) inherit the parent's lock rather than deadlocking.
2. Assembles the LLM's system message from context blocks (in defined order) plus the strategy's own prompt contribution, and the conversation from event history (filtered by `EventQuery` if one applies).
3. Dispatches to whichever `GenerationStrategy` is attached to the method — explicit via `@strategy(...)`, or `get_default_strategy()` (process-wide default, `CodeActStrategy` unless changed via `set_default_strategy()`).
4. Validates the strategy's result against the method's return type annotation, retrying (strategy-dependent, typically up to `max_retries`) with the validation error surfaced to the model if it doesn't match.
5. Records every step as an event on `self.event_manager`.

See [`concepts/strategies.md`](strategies.md) for what happens inside step 3, and [`concepts/execution-and-storage.md`](execution-and-storage.md) for what backs step 1's event-sourcing guarantee.

### `@strategy` decorator

`strategy()` (`src/nooa/decorators.py`) is how you override the strategy, LLM, context, or truncation config for one specific method, without touching its signature:

```python
def strategy(
    strategy_instance: "GenerationStrategyABC | None" = None,
    context: "ScopedContext | dict[str, Any] | None" = None,
    *,
    llm: "UnifiedLLM | None" = None,
    truncation: "TruncationConfig | None" = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]
```

`context` accepts either a plain dict of context-block overrides (`{"focus": "security", "self": None}` — `None` removes a block) applied for the duration of that method's call, or a `ScopedContext` when you also need to filter which *events* are visible (`ScopedContext(context={...}, events=EventQuery.current_call())`). Only one `@strategy` decorator may be stacked on a method — a second raises `ValueError`.

`@strategy` also has a standalone-function mode: if the decorated function's first parameter isn't `self`, it becomes a **standalone generation function** — each call creates a fresh, stateless agent stub with no persistent state or history, useful for one-off LLM calls that don't warrant a full class (`src/nooa/standalone.py`).

### Templating: docstrings are f-strings

Both class docstrings (system prompt) and method docstrings (task prompt) support `{expression}` placeholders, resolved as Python expressions evaluated in a namespace containing `self`:

```python
async def translate(self, text: str) -> str:
    """Translate the text to {self.target_language}.

    Keep the translation natural and idiomatic.
    """
    ...
```

Any expression works — `{self.attr}`, `{len(items)}`, `{param.upper()}` — evaluated fresh at call time, so one method definition serves many runtime-configured behaviors. The reserved caveat: **method parameters are already shown to the model by the strategy's own argument rendering** (CodeAct's default prefill pretty-prints every parameter; Predict serializes them with size caps) — re-injecting a raw parameter into the docstring text via `{param}` duplicates it untruncated and moves untrusted data into the instruction channel. Reserve `{...}` for what the signature can't show: instance state (`{self.attr}`) and computed expressions (`{len(items)}`), not raw arguments (see `AGENTS.md`).

If a placeholder's expression raises, the literal `{expr}` text (with any conversion/format-spec suffix) is left in place rather than crashing prompt assembly — a defensive fallback in `Agent._resolve_system_prompt()` and the equivalent method-docstring path.

### The `reasoning` reserved parameter

Declaring a generation-method parameter literally named `reasoning` raises `ValueError` at class creation — it's reserved for the framework's own `reasoning()` builtin available inside CodeAct-generated code (chain-of-thought). Use a different name (`rationale`, etc.) for a parameter that happens to need that word.

## Orchestrators are just Python

Nothing requires every method on an `Agent` subclass to be a generation method. A class whose methods are all real-bodied Python doesn't even need to subclass `Agent`. The recommended pattern (`AGENTS.md`) is: **orchestrators are pure Python** — a workflow-sequencing method with a real body calls generation methods for each LLM-driven step:

```python
async def run(self, expression: str) -> str:
    """Orchestrator: evaluate, then explain."""
    value = await self.calculate(expression)      # generation method
    formatted = await self._format(value)          # deterministic helper
    return await self.explain(expression, formatted)  # generation method

async def calculate(self, expression: str) -> float:
    """Evaluate the mathematical expression and return the numeric result."""
    ...
```

`run` itself is traced (parent span), and `calculate`/`_format`/`explain` show up as nested child spans — because tracing follows the Python call graph, not a chat transcript. See [`concepts/tracing-and-observability.md`](tracing-and-observability.md).

## Design guidance (method-level rules)

From `AGENTS.md`, reproduced here because they follow directly from the mechanics above:

- **One method = one LLM task.** A method that classifies, greps, and summarizes should be three methods, not one — each generation method is one prompt, and mixing responsibilities produces a prompt trying to do three jobs at once.
- **Helpers beat prompts.** If logic can be deterministic Python, make it a real method rather than an instruction telling the model how to compute it — deterministic code is faster, cheaper, and can't be gotten "almost right."
- **Evidence before assertions.** An orchestrator that claims a task is done should have actually run verification first (tests, checks) — enforce this in orchestrator code, not by asking the model nicely in a docstring.

## Related

- [`concepts/strategies.md`](strategies.md) — what actually happens when a generation method's strategy runs.
- [`concepts/visibility-and-context.md`](visibility-and-context.md) — what `doc(self)` shows the model, and how context blocks assemble the system prompt.
- [`guides/write-your-first-agent.md`](../guides/write-your-first-agent.md) — task-oriented walkthrough of writing one from scratch.
- `skills/nooa-agent-authoring/SKILL.md` in the repo — the coding-agent-facing version of this same material, kept terser for fast lookup while writing code.
