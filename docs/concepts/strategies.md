# Strategies

A `GenerationStrategy` is the pluggable engine that decides *how* a generation method's task gets solved — one LLM call vs. an iterative code-execution loop, retried validation vs. single-shot, and so on. Tracks `src/nooa/strategies/*`, `src/nooa/strategy_validation.py`, `src/nooa/config/strategy_config.py`.

## The abstraction

Every strategy subclasses `GenerationStrategy` (`src/nooa/strategies/base.py`), an ABC with one required method:

```python
async def execute(self, runtime: RuntimeServices, call: "CurrentCall") -> Any: ...
```

`RuntimeServices` is the protocol a strategy is handed instead of the raw agent — a clean dependency boundary exposing:

- `generate(*, tools=None, output_model=None, **kwargs)` — build messages from context blocks + event history, call the LLM, record an `LLMOutput` event, return `(LLMResponse, event_id)`.
- `execute_code(code, *, builtins=None, validate=True, timeout=90.0, restrictions=None, ...)` — validate and run Python (AST checks, then in-process or sandboxed execution), returning an `ExecutionResult` with stdout/error/defined_methods.
- `execute_nested(strategy, call)` — run another strategy within the *current* generation session (inherits the lock, avoids deadlock) — how composite strategies like Reflexion wrap a base strategy.
- `get_generation_id()` / `get_parent_generation_id()` — correlate events across nested generation calls.
- `expand_variables(text, extra_context=None, error_mode="show")` — the `{expression}` docstring-templating engine (see [`concepts/agents-and-generation-methods.md`](agents-and-generation-methods.md)).
- `truncation_config` — the resolved `TruncationConfig` for the current agent/method.

Every strategy also exposes:

- `.name` — defaults to the class name; used in traces/logs.
- `.get_block_overrides()` — context-block overrides the strategy itself wants applied (e.g. injecting a `strategy_prompt` dynamic block describing available tools).
- `.get_block_order()` — optional reordering of system-role context blocks.
- `.traceable` — `True` by default; strategies that never call an LLM (`TemplateStrategy`) override to `False` to suppress noisy spans.
- `.requires_lock` — `True` by default (serialized LLM access); a stateless strategy could override to `False`.

## The strategy catalogue

| Strategy | Calls an LLM? | Iterates? | Use for | Status |
|---|---|---|---|---|
| **`CodeActStrategy`** (default) | Yes | Yes — Python REPL loop | Tool use, multi-step reasoning, anything needing to run code | Stable |
| **`PredictStrategy`** | Yes | No — single shot + validation retry | Classification, extraction, anything solvable in one structured call | Stable |
| **`TemplateStrategy`** | No | No | Pure string templating (`{expr}` expansion) with no model call at all — the foundation other strategies build on | Stable |
| **`CompositeStrategy`** | Depends on wrapped strategy | Depends | Base class for strategies that wrap/compose another strategy | Stable (base class) |
| **`ReflexionStrategy`** | Yes | Yes — solve, critique, retry | Self-critique loops | **Experimental** — importing from `nooa.strategies` is warning-free; importing from top-level `nooa` or `nooa.experimental` emits `FutureWarning`. Recommendation: use `CodeActStrategy` or `PredictStrategy` instead. |
| **`CodeActLiteStrategy`** | Yes | Yes | A lighter-weight CodeAct variant | **Experimental** — same warning gate as above |
| **`PurePythonStrategy`** | Yes | Yes | Pure-Python execution variant | **Experimental**, only reachable via `nooa.experimental.PurePythonStrategy(...)` |

### `CodeActStrategy` (default)

The LLM reasons inside an iterative, Jupyter-style Python REPL: it's given an `execute_python()` tool plus a structured `return_result()` exit, writes code (which can freely call other methods on `self` — no separate tool schema needed), observes stdout/results, and repeats until it calls `return_result(value)` with something matching the method's return type — or the loop is stopped by a guard. Reference: "Executable Code Actions Elicit Better LLM Agents" (Wang et al.), cited directly in `src/nooa/strategies/codeact.py`.

Configured via `CodeActConfig` (`src/nooa/config/strategy_config.py`), the fields worth knowing:

| Field | Default | Meaning |
|---|---|---|
| `max_iterations` | `None` (unbounded) | Cap on REPL turns before the run is forced to stop |
| `max_retries` | `3` | Validation-failure retries |
| `max_consecutive_text_only` | `3` | Consecutive turns where the model replies with plain text instead of a tool call before the run aborts (`0` disables the guard) |
| `text_only_stop_behavior` | `"return_result"` | How a `finish_reason="stop"` (text-only) response is handled — routed through `return_result()` validation (recommended; breaks loops faster) or converted to a synthetic no-op comment |
| `cell_timeout` | `None` | Per-cell execution timeout (seconds) |
| `max_tokens` / `temperature` / `top_p` | `None` | Sampling overrides |
| `max_tool_calls` | `None` | Cap on total tool calls |
| `restrictions` | `RestrictionsConfig()` | Module/call deny-list for generated code — see [`concepts/execution-and-storage.md`](execution-and-storage.md) |
| `execution_backend` | `"inprocess"` | `"inprocess"` runs cells in the agent's own event loop; `"sandbox"` runs each cell in a locked-down worker process with OS-enforced timeout/memory/CPU/filesystem/network limits — turns `cell_timeout` into a hard bound |
| `sandbox` | `SandboxConfig()` | Ignored unless `execution_backend="sandbox"` |
| `preconditions` / `postconditions` | `()` | Method-local deterministic validators (`nooa.strategy_validation`) — preconditions run before generation (fail fast), postconditions run after return-type validation and raise `InvariantError` for a model-correctable retry |
| `prefill` | `InspectInputsPrefill()` | A synthetic "first turn" run before the main loop — default auto-renders every parameter via `pformat`; `None` disables prefill entirely |

```python
from nooa.decorators import strategy
from nooa.strategies import CodeActStrategy
from nooa.config import CodeActConfig

@strategy(CodeActStrategy(config=CodeActConfig(max_iterations=10, execution_backend="sandbox")))
async def perform_task(self, request: str) -> str:
    """Perform the task requested by the user."""
    ...
```

### `PredictStrategy`

A single, non-iterative LLM call. `PredictStrategy` inspects the method's return type annotation, converts it to a Pydantic model if it isn't already one (wrapping bare types like `str`/`int`/`bool`/`dict`/`list`, unwrapping `Optional[T]`), calls the LLM with that as the structured-output schema, and validates the response — retrying with the validation error surfaced to the model on failure, up to `PredictConfig.max_retries`.

```python
from nooa.decorators import strategy
from nooa.strategies import PredictStrategy
from nooa.config import PredictConfig

@strategy(PredictStrategy(config=PredictConfig(max_retries=3)))
async def classify_sentiment(self, text: str) -> str:
    """Classify as positive, negative, or neutral."""
    ...
```

### `TemplateStrategy`

No LLM call at all — pure string templating via `runtime.expand_variables()`. This is the strategy every other strategy's own internal prompt-building (e.g. constructing an error message with `{method}`/`{line}` placeholders) is built on top of; you'd reach for it directly only for a method that's genuinely just deterministic string formatting but still wants to go through the generation-method call path (e.g. to get traced, or to participate in composite strategies).

### `CompositeStrategy`

The base class for strategies that wrap another strategy rather than solving a task themselves — e.g. Reflexion wraps a base strategy with a solve → critique → retry loop, calling the wrapped strategy via `runtime.execute_nested()` so the nested call shares the parent's generation lock instead of deadlocking.

## Choosing a strategy

The one decision that matters most: **does this task need to run code / call tools / iterate, or can a single structured call solve it?**

- If the task is "read this text, produce this classification/extraction" and nothing else — no lookups, no computation, no multi-step reasoning — use `PredictStrategy`. It's cheaper (one call) and faster.
- If the task needs to call other methods on `self`, do arithmetic, loop over data, or reason across multiple steps before it can answer — use `CodeActStrategy` (the default; you often don't need to write `@strategy` at all).
- Advanced/experimental needs (self-critique loops) exist behind `ReflexionStrategy`, but the framework's own guidance is to prefer `CodeActStrategy` or `PredictStrategy` unless you have a specific reason not to.

See [`guides/choose-a-strategy.md`](../guides/choose-a-strategy.md) for a worked decision checklist.

## Setting a default

`get_default_strategy()` / `set_default_strategy()` (`src/nooa/strategies/__init__.py`) control the process-wide (technically: current-`ContextVar`-scoped) default used when a generation method has no `@strategy` override — a fresh `CodeActStrategy(config=CodeActConfig())` unless changed. Useful for evaluation pipelines that want to A/B every agent under a fixed strategy without editing every class:

```python
from nooa import set_default_strategy, CodeActStrategy
from nooa.config import CodeActConfig

set_default_strategy(CodeActStrategy(config=CodeActConfig(max_iterations=10)))
# ... run evaluation; every agent without an explicit @strategy uses this ...
set_default_strategy(None)  # reset to library default
```

## Advanced: self-extending agents and standalone strategy calls

Inside a `CodeActStrategy` loop, the LLM can define brand-new `@strategy(...)`-decorated methods at runtime (typically `PredictStrategy` sub-calls for fan-out work) and invoke them — e.g. defining a per-item `extract_features` helper and running it over a list via `asyncio.gather`. `@strategy` on a function whose first parameter is *not* `self` creates a **standalone** wrapper instead — each call spins up a fresh, stateless agent stub with no persistent state, which is how these ad hoc sub-calls avoid polluting the calling agent's own history. See `skills/nooa-self-extending/SKILL.md` for the full pattern.

## Related

- [`concepts/agents-and-generation-methods.md`](agents-and-generation-methods.md) — how a generation method gets to a strategy in the first place.
- [`concepts/execution-and-storage.md`](execution-and-storage.md) — what backs `execute_code()`'s validation and sandboxing.
- [`reference/configuration-reference.md`](../reference/configuration-reference.md) — every `CodeActConfig`/`PredictConfig` field.
- `skills/nooa-codeact-advanced/SKILL.md` in the repo — prefill tuning, loop guards, truncation tuning, code restrictions, execution internals.
