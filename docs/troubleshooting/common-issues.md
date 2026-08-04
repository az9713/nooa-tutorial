# Troubleshooting: Common Issues

Symptom → cause → fix, for the problems you're most likely to hit working with NOOA. If your issue isn't here, check the specific concept doc it relates to, or `AGENTS.md` for the terse rule that might explain it.

## Setup and installation

### `ModuleNotFoundError: No module named 'nooa'`

**Cause:** either the package isn't installed in the environment you're running, or (inside the cloned repo) you're not running through `uv run`.

**Fix:**
```bash
uv add nooa                      # fresh project
# — or, inside the cloned repo —
uv sync --group dev
uv run python your_script.py     # always prefix with `uv run` inside the repo
```

### `ImportError` mentioning a missing extra (`fastapi`, `mcp`, `opentelemetry`, ...)

**Cause:** you're using a feature that lives behind an optional extra — the core `nooa` install deliberately ships with only three runtime dependencies (`pydantic`, `litellm`, `httpx`).

**Fix:** install the matching extra — see the table in [`getting-started/prerequisites.md`](../getting-started/prerequisites.md#optional-install-only-when-you-need-them). Common ones: `uv add "nooa[cli]"` (trace viewer/CLI), `uv add "nooa[mcp]"` (MCP tools), `uv add "nooa[tracing]"` (third-party trace export), `uv add "nooa[sandbox]"` (sandboxed execution).

### `nooa eval` fails with a message about `eval_pipeline` not installed

**Cause:** `eval_pipeline` ships with the monorepo workspace but is not a dependency of the standalone `nooa-cli` wheel.

**Fix:**
```bash
uv add "eval_pipeline @ git+https://github.com/NVIDIA-NeMo/labs-OO-Agents.git@main#subdirectory=util/eval_pipeline"
```

## Constructing agents

### `ValueError: No LLM available for <ClassName>`

**Cause:** cascading LLM resolution failed at all three steps — no instance-level `llm=`, no class-level `llm=`, and no parent agent in scope (see [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md#cascading-llm-resolution)).

**Fix:** pass `llm=my_llm` to `__init__`, or set it in the class definition (`class MyAgent(Agent, llm=my_llm)`), or confirm the agent really is being instantiated inside a parent agent's generated code if you're relying on runtime propagation.

### `ValueError: <ClassName>: llm=None is not allowed`

**Cause:** you passed `llm=None` explicitly, which is a hard error — `None` is reserved to mean "explicitly disable," which isn't supported; omitting the parameter is how you opt into cascading.

**Fix:** either omit `llm=` entirely (enables cascading resolution) or pass an actual `UnifiedLLM` instance.

### `ValueError` about a parameter named `reasoning`

**Cause:** `reasoning` is a reserved generation-method parameter name — the framework reserves it for the `reasoning()` builtin available inside CodeAct-generated code.

**Fix:** rename the parameter (e.g. `rationale`).

## Generation methods not behaving as expected

### The model never calls a helper method I defined

**Cause:** almost always one of two things — the method is hidden from the LLM (name starts with `_` and isn't opted back in with `@spec(hidden=False)`, or it's explicitly `@hidden`), or the docstring never tells the model to use it (`doc()` shows *that* it exists, not *when* to use it).

**Fix:** confirm visibility (see [`concepts/visibility-and-context.md`](../concepts/visibility-and-context.md)) with a quick check:
```python
from nooa.agentdoc import doc
print(doc(agent))   # confirm the method appears
```
Then make sure the calling method's docstring explicitly references it by name.

### Validation keeps retrying and never returns / eventually raises `GenerationError`

**Cause:** the return type annotation is stricter than the model can reliably satisfy — a narrow `Literal[...]`, an over-constrained Pydantic field, or ambiguous docstring guidance about which value to pick.

**Fix:** loosen the type, add explicit docstring guidance for edge cases, or (for `PredictStrategy`) raise `max_retries` in `PredictConfig` as a stopgap while you diagnose the underlying strictness mismatch. See [`guides/choose-a-strategy.md`](../guides/choose-a-strategy.md).

### CodeAct method hits `max_iterations` and aborts

**Cause:** either the task genuinely needs more turns than the configured ceiling, or the docstring is ambiguous about when the task counts as "done," causing the model to loop without converging.

**Fix:** first check the trace (`nooa start-dev`) to see what the model was doing on the later iterations — looping on the same failed approach usually means a docstring/task clarity problem, not an iteration-count problem. If the task is legitimately multi-step and just needs more room, raise `CodeActConfig(max_iterations=...)`.

### Renaming a method changed its output and I didn't expect that

**Cause:** this is expected, not a bug — the method name is part of the prompt (see [`overview/what-is-this.md`](../overview/what-is-this.md), idea 2). `analyze_feedback` and `analyze_feedback_briefly` are different prompts even with identical bodies.

**Fix:** none needed — if you don't want a rename to change behavior, keep the docstring fully explicit about the desired behavior rather than relying on the method name to convey nuance.

### A docstring `{param}` placeholder shows raw/untruncated data or looks redundant

**Cause:** method parameters are already shown to the model by the strategy's own argument rendering (CodeAct's default prefill, Predict's parameter serialization) — reinjecting `{param}` into the docstring text duplicates it, untruncated, and moves untrusted data into the instruction channel.

**Fix:** remove the `{param}` reference; reserve `{...}` templating for instance state (`{self.attr}`) and computed expressions (`{len(items)}`) that the signature can't already show. See [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md#templating-docstrings-are-f-strings).

## Tracing and the viewer

### Nothing shows up in the trace viewer

**Cause:** most commonly, the viewer wasn't running *before* the agent was constructed — `_try_auto_enable_tracing()` does a one-time-per-process reachability check at first `Agent()` construction, so starting the viewer afterward won't retroactively catch that run.

**Fix:** always start `uv run nooa start-dev` first, in its own terminal, before running the script you want to trace. Also check `OTLP_ENDPOINT` isn't set to something else, redirecting spans elsewhere.

### `nooa start-dev` fails — port already in use

**Cause:** another process (possibly a previous `start-dev` you forgot about) is bound to port 5001.

**Fix:** `start-dev` reports the PID holding the port; stop it, or run on another port: `uv run nooa start-dev --port 5002`.

### A method I expected to see in a trace is missing

**Cause:** it's marked `@no_trace`, or it was never actually called (verify with a temporary `print()` if unsure).

**Fix:** remove `@no_trace` if the method should be traced; otherwise confirm your assumption about the call path is correct.

## Tools, skills, and MCP

### MCP connection fails before any tool call happens

**Cause:** failing at the MCP session layer, not the agent/model layer — wrong URL/transport, missing auth headers, or a slow server exceeding the 5-second connect timeout.

**Fix:** verify the transport (`"sse"`/`"stdio"`/`"streamable-http"`) and URL/headers match what the server expects; see [`guides/connect-an-mcp-server.md`](../guides/connect-an-mcp-server.md).

### An MCP tool or skill attribute never shows up in `doc(agent)`

**Cause:** either the attribute is hidden (name starts with `_`, or `@hidden`), or its construction raised an exception at class-definition time that got swallowed somewhere upstream.

**Fix:** check visibility first; if still missing, try constructing the same object standalone (`MCPManager.create_from_server(...)` outside the class body) to see if it raises.

## Code execution and safety

### `RestrictedCodeError` on generated code that "should" be fine

**Cause:** the code imports or calls something on the default deny-list (`subprocess`, `socket`, `http.client`, `urllib.request`, `ftplib`, etc. — see [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md)) or a custom `restricted_imports` entry your project set.

**Fix:** if the blocked capability is genuinely needed and you understand the tradeoff, either provide it as a deterministic helper method instead of letting the model reach for the raw module (usually the better fix — see "helpers beat prompts" in [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md)), or narrow the restriction via `set_restricted_imports(...)` if you're confident about your isolation posture (only inside an already-sandboxed/OS-isolated environment).

### I need stronger isolation than the default in-process execution gives me

**Cause:** you're running agents whose generated code touches untrusted input, or you simply want a stronger boundary than AST validation + deny-lists provide (which, by design, is not a security boundary — see [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md)).

**Fix:** set `CodeActConfig(execution_backend="sandbox", sandbox=SandboxConfig(...))` for per-cell kernel-enforced isolation, and/or run the whole agent process inside a container/VM or [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) for full containment. Per-cell sandboxing alone is not a substitute for isolating the whole process if the input is genuinely untrusted.

## Running the test suite (contributors)

### `pytest` fails to collect / import errors across many test files

**Cause:** usually a stale or incomplete `uv sync` — the test suite spans the core package plus workspace packages (`packages/nooa-cli`, `packages/nooa-bench`), all of which need to be installed together.

**Fix:**
```bash
uv sync --group dev
uv run pytest
```

### A test I'm not touching is skipped or fails with a marker-related message

**Cause:** the default `pytest` invocation excludes `integration` and `stress` marked tests (`addopts = "... -m 'not integration and not stress'"` in `pyproject.toml`) — they make real API calls or simulate high concurrency.

**Fix:** this is expected for the default run; run them explicitly if you need to (`uv run pytest -m integration`), understanding they'll make real network/API calls.

## Still stuck?

- Re-check the relevant concept doc — this page covers symptoms, the concept docs cover the mechanism that produces them.
- `AGENTS.md` at the repo root has the terse, rule-based version of most of the guidance above.
- The eleven `skills/*/SKILL.md` bundles (index: `skills/README.md`) go deeper on specific subsystems than this troubleshooting page does.
- For an actual bug in the framework, open an issue per [`../CONTRIBUTING.md`](../../CONTRIBUTING.md).
