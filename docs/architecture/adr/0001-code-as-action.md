# ADR 0001: CodeAct as the Default Generation Strategy

## Status

Accepted (reflects the shipped default as of this writing — `get_default_strategy()` returns `CodeActStrategy()` unless overridden; see `src/nooa/strategies/__init__.py`).

## Context

When a generation method needs to do more than answer directly from its prompt — look something up, call other methods, reason across multiple steps, use an external tool — the strategy handling that method needs some mechanism for the model to take intermediate actions before producing a final answer. Two broad approaches exist in the field:

1. **Structured function-calling**: the model is given a fixed menu of tool schemas (JSON Schema function definitions) and picks one per turn, with arguments as structured JSON. This is what most LLM provider APIs expose natively as "tool use" / "function calling."
2. **Code-as-action (CodeAct)**: the model is given a code-execution tool and writes actual Python to accomplish sub-tasks — including calling arbitrary other functions/methods — rather than picking from a discrete, pre-declared menu. Reference: "Executable Code Actions Elicit Better LLM Agents" (Wang et al.), cited directly in `src/nooa/strategies/codeact.py`.

NOOA needed to pick a default for `CodeActStrategy` vs. a hypothetical structured-function-calling-first strategy, given that the rest of the framework's design (methods-as-tools, no separate tool-schema layer) already leans toward one of these.

## Decision

Default every generation method to `CodeActStrategy` unless the author explicitly opts into `PredictStrategy` (single-shot, structured-output-only) via `@strategy(PredictStrategy())`.

## Rationale

- **Methods-as-tools only works cleanly with code-as-action.** The framework's central premise — "any regular method on `self` is automatically a tool, no schema required" — is straightforward for code-as-action (the model just writes `self.get_stock("apple")`, the same as any Python call) but awkward for structured function-calling, which would require auto-generating a JSON Schema per method from its signature and keeping that generation correct across arbitrary Python type annotations. CodeAct sidesteps that translation layer entirely: the model already knows how to call a Python method because it's writing Python.
- **Composability of tool calls.** Structured function-calling typically does one tool call per turn, evaluated in isolation; CodeAct lets the model combine several calls, loop, branch, and post-process results within a single cell before deciding what to do next — closer to how a human engineer would actually solve a multi-step task.
- **Progressive disclosure (`doc()`) pairs naturally with code-as-action.** Since the model can call `doc(some_object)` on anything it holds a reference to and then write code against the discovered shape, CodeAct lets an agent operate on types it's never been told about in its system prompt — a capability that has no clean equivalent in a fixed-schema function-calling menu, where every callable surface has to be declared upfront.
- **Empirical grounding.** The framework's paper reports SWE-bench Verified and Terminal-Bench 2.0 results (reproducible via `nooa-bench`'s Harbor runner) that motivate CodeAct as the stronger default for the kinds of multi-step, tool-heavy tasks the framework targets, consistent with the broader "Executable Code Actions Elicit Better LLM Agents" finding CodeAct itself is based on.

## Consequences

- **Structured function-calling isn't gone — `PredictStrategy` covers the single-shot case.** For tasks that genuinely don't need iteration (classification, extraction), `PredictStrategy` is a one-call, non-code-execution alternative, and the framework recommends switching to it explicitly rather than paying CodeAct's iteration overhead for tasks that don't need it (see [`guides/choose-a-strategy.md`](../../guides/choose-a-strategy.md)).
- **Code execution requires a validation/sandboxing story CodeAct's structured-function-calling alternative wouldn't have needed.** Because the model can write arbitrary Python, not just fill in a fixed schema, NOOA needs the AST-validation, module-deny-list, and optional sandboxed-execution-backend machinery described in [`concepts/execution-and-storage.md`](../../concepts/execution-and-storage.md) — machinery a pure structured-function-calling design wouldn't need at all, since its "actions" are bounded to whatever a small set of declared schemas allow. This is the direct cost of the decision: more capability, but a materially larger safety surface, which is why the framework carries the "research software — run in an isolated environment" warning as prominently as it does.
- **Debugging looks like debugging code, not like reading a chat log.** A side effect of choosing CodeAct as default is that tracing (see [`concepts/tracing-and-observability.md`](../../concepts/tracing-and-observability.md)) naturally surfaces executed cells and their stdout/output as first-class trace content, not just message text — a byproduct of the strategy choice that shaped how the trace viewer itself was designed to present a run.

## Alternatives considered

- **Structured function-calling as the default, CodeAct as opt-in.** Rejected as the *default* because it would have required either a schema-generation layer bridging Python method signatures to JSON Schema (adding exactly the "second thing to keep in sync" the framework's broader design avoids) or restricting the tool surface to a hand-curated subset of methods per agent (undermining "any method is automatically a tool"). It remains available in spirit via `PredictStrategy` for the no-iteration case, though Predict doesn't expose a tool-calling loop at all — it's a genuinely different shape of solution, not structured-function-calling-with-iteration.
- **No default strategy — require every generation method to declare one explicitly.** Rejected for the same reason implicit `...`-detection was chosen over a required decorator: it adds ceremony to the common case (most generation methods are fine with the default) in exchange for explicitness that most authors won't need often enough to justify the tax.
