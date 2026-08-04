# Guide: Trace and Debug a Run

**Goal:** turn on tracing, view a live run in the trace viewer, and use the call-tree structure to find where an agent went wrong.

## Prerequisites

- The `nooa-cli` / `viewer` extra installed — if you did `uv sync --group dev` in the cloned repo you already have it; standalone, `uv add nooa-cli`.
- Read [`concepts/tracing-and-observability.md`](../concepts/tracing-and-observability.md) for what a span actually represents.

## Steps

### 1. Start the trace viewer

```bash
uv run nooa start-dev
```

Expected output:

```
Uvicorn running on http://127.0.0.1:5001 ...
```

If the port's already taken, either stop whatever's using it (`start-dev` will tell you the PID it found) or pick another port:

```bash
uv run nooa start-dev --port 5002
```

### 2. Run your agent script in a separate terminal

Tracing auto-enables the moment any `Agent` is constructed, as long as the viewer is reachable — no code change needed:

```bash
uv run python your_agent_script.py
```

### 3. Open the run in the browser

Navigate to `http://localhost:5001` (or your custom port). You should see the run listed, with a nested span tree matching your agent's call structure — orchestrator methods as parent spans, generation methods and helper methods as nested children, in the same order and nesting as your Python call graph.

### 4. Read a CodeAct span

For any span backed by `CodeActStrategy`, expand it to see: the assembled prompt (context blocks + docstring + event history), each `execute_python()` cell the model ran (code, stdout, any error), and the final `return_result(...)` call. This is the fastest way to answer "why did the model produce this output" — you're looking at exactly what it saw and exactly what it did, not a reconstruction.

### 5. Narrow down a specific call programmatically (optional)

For anything beyond visual inspection — searching many runs, extracting specific fields, feeding results into a script — use `TraceExplorer` instead of the UI:

```python
from nooa.trace_explorer import TraceExplorer

trace = await TraceExplorer.from_file("traces/your_session.jsonl")
print(await trace.get_overview())
errors = (await trace.search("Error")).matches  # illustrative — see TraceExplorer's actual API for exact method names
```

If you didn't set an explicit `exporters.jsonl(...)` destination, zero-config tracing writes JSONL under `./traces/` (or `$TRACE_DIR`) as a fallback whenever the viewer isn't reachable — check there if you're not sure where a session's file landed.

### 6. Export somewhere durable if you need to keep the trace

By default, zero-config tracing talks to the viewer over OTLP and falls back to local JSONL — neither is meant as long-term storage. For anything you want to keep or share, export explicitly:

```python
from nooa.tracing import enable_tracing, exporters

enable_tracing(exporters=[exporters.jsonl("./traces/my_run")])
# or send to a third-party backend:
enable_tracing(exporters=[exporters.otlp("http://localhost:4318/v1/traces")])
enable_tracing(exporters=[exporters.langfuse()])  # reads LANGFUSE_* env vars
```

## Verification

- The run you executed in Step 2 appears in the viewer within a few seconds of the script finishing (or live, as it runs).
- Expanding an orchestrator span shows exactly the child methods you expect, in the order you expect — if a method you know was called doesn't appear, check it isn't marked `@no_trace`.
- For a CodeAct span, the code shown under "executed cells" is code the *model* wrote, not code you wrote — if it looks unfamiliar, that's expected and is exactly the point of tracing this strategy.

## Troubleshooting

- **Nothing shows up in the viewer** — confirm the viewer was already running *before* the agent script started (tracing does a reachability check once per process at agent construction time; starting the viewer after the script has already run won't retroactively catch that run). Also confirm you didn't set `OTLP_ENDPOINT` to something else, redirecting spans away from the local viewer.
- **A method call I expected to see is missing** — check for `@no_trace` on it; also confirm it's actually being called at all (add a temporary `print()` if unsure) rather than assuming tracing dropped it.
- **Traces from two different runs seem to have colliding span IDs** — this was specifically addressed by using an isolated RNG for span/trace ID generation (`_IsolatedIdGenerator` in `src/nooa/tracing/`), decoupled from the process-global `random` module, precisely because generated code calling `random.seed(...)` used to cause this. If you still see it, you may be on an older version — check `nooa --version` / `CHANGELOG.md`.
- **The viewer won't start — port already in use** — `nooa start-dev` reports the PID holding the port (via `lsof`/`ss`); decide whether to stop it or use `--port`.
- General issues: [`troubleshooting/common-issues.md`](../troubleshooting/common-issues.md). Deeper viewer/explorer usage: `skills/nooa-trace-viewer/SKILL.md`, `skills/nooa-trace-explorer/SKILL.md` in the repo.
