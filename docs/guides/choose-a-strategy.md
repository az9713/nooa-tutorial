# Guide: Choose a Strategy for a Generation Method

**Goal:** decide which `GenerationStrategy` to attach to a given generation method (or confirm the default is already right), and configure it sensibly.

## Prerequisites

Read [`concepts/strategies.md`](../concepts/strategies.md) first — this guide is the decision checklist; that doc is the reference for what each strategy actually does and every config field.

## Steps

### 1. Ask: does this method need to call other methods, execute logic, or iterate?

Walk through your method's docstring/task and answer honestly:

- Does it need to look something up, compute something, or call another method on `self` before it can answer? → **Yes: keep the default, `CodeActStrategy`.** You usually don't need to write `@strategy` at all.
- Is it purely "read this input, produce this classification/extraction/short answer" with nothing else needed? → **No: use `PredictStrategy`.**

```python
# No tool calls needed, one clean structured output — PredictStrategy
@strategy(PredictStrategy())
async def classify_sentiment(self, text: str) -> str:
    """Classify as positive, negative, or neutral."""
    ...

# Needs to call self.get_stock / self.get_price, reason across items — CodeActStrategy (default, no decorator needed)
async def can_fulfill_order(self, items: list[str], budget: float) -> Result:
    """Check if order can be fulfilled within budget."""
    ...
```

### 2. If CodeAct: set bounds appropriate to the task

Don't leave `max_iterations=None` (unbounded) for a production method — pick a ceiling based on how many tool-call round-trips the task should reasonably need:

```python
from nooa.config import CodeActConfig
from nooa.strategies import CodeActStrategy

@strategy(CodeActStrategy(config=CodeActConfig(
    max_iterations=10,        # hard ceiling on REPL turns
    cell_timeout=30.0,        # per-cell timeout in seconds
)))
async def perform_task(self, request: str) -> str:
    """Perform the task requested by the user and provide a friendly response."""
    ...
```

If the method's own retries matter more than iteration count (e.g. flaky structured output), also look at `max_retries` (validation-failure retries, default 3) and `max_consecutive_text_only` (default 3 — how many turns of plain text without a tool call before the run aborts).

### 3. If Predict: set retry limits based on how strict your return type is

```python
from nooa.config import PredictConfig

@strategy(PredictStrategy(config=PredictConfig(max_retries=3)))
async def analyze(self, data: str) -> AnalysisResult:
    """Analyze data and return structured results."""
    ...
```

A narrow `Literal[...]` or heavily-constrained Pydantic model may need more retries than a loose `str` — if you see runs consistently exhausting retries, that's a signal the type is stricter than the model can reliably hit, not necessarily that retries need raising further (see Troubleshooting).

### 4. Need code execution but want it isolated from the host process?

Set `execution_backend="sandbox"` and configure `SandboxConfig` — see [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md) for the full guardrail table (timeout/memory/CPU/filesystem/network) and why this is still not a substitute for OS-level isolation of the whole process.

```python
from nooa.runtime.sandbox.config import SandboxConfig

@strategy(CodeActStrategy(config=CodeActConfig(
    execution_backend="sandbox",
    sandbox=SandboxConfig(max_memory_mb=512, max_cpu_seconds=30, network=False),
)))
async def process_untrusted_input(self, data: str) -> str:
    """Process the input."""
    ...
```

### 5. Only reach for Reflexion/CodeActLite/PurePython if you have a specific, tested reason

These are marked experimental in the framework itself — importing them from `nooa.experimental` (or top-level `nooa`) emits a `FutureWarning`, and the framework's own recommendation is to use `CodeActStrategy` or `PredictStrategy` instead. If you're tempted by Reflexion's solve-critique-retry loop, first check whether raising `max_iterations` on `CodeActStrategy` (which already lets the model self-correct across turns) gets you the same result with a stable, maintained strategy.

### 6. Set a process-wide default only for evaluation/testing contexts

Don't use `set_default_strategy()` to change production behavior implicitly — it's meant for scoped evaluation runs:

```python
from nooa import set_default_strategy, CodeActStrategy
from nooa.config import CodeActConfig

set_default_strategy(CodeActStrategy(config=CodeActConfig(max_iterations=5)))
# run your eval suite — every agent without an explicit @strategy uses this
set_default_strategy(None)  # always reset afterward
```

## Verification

- Run the method once with tracing on (`uv run nooa start-dev`, then re-run your script) and check in `http://localhost:5001` how many LLM calls it actually made. A `PredictStrategy` method should show exactly one; a `CodeActStrategy` method should show a bounded, sensible number of turns — if it's regularly hitting your `max_iterations` ceiling, either the ceiling is too low for the task or the task needs decomposing into smaller methods (see [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md) — "one method = one LLM task").
- Confirm cost/latency moved the direction you expected: swapping a classification method from `CodeActStrategy` to `PredictStrategy` should visibly reduce both LLM call count and wall-clock time for that method.

## Troubleshooting

- **Predict method exhausts `max_retries` on a valid-seeming input** — the return type is likely stricter than the model can reliably satisfy zero-shot. Loosen a `Literal` set, relax a numeric constraint, or add explicit guidance in the docstring about edge cases, rather than only raising `max_retries`.
- **CodeAct method runs many more iterations than expected** — check whether the docstring is ambiguous about when the task is "done," and whether `text_only_stop_behavior="return_result"` (the default) is actually routing plain-text replies through validation as intended.
- **Switching strategies changed the method's behavior in a way that broke callers** — it shouldn't, by design (see [`overview/what-is-this.md`](../overview/what-is-this.md), idea 4). If it did, the return type annotation likely wasn't tight enough to fully pin down the contract both strategies validate against — tighten it.
- General strategy issues: [`troubleshooting/common-issues.md`](../troubleshooting/common-issues.md).
