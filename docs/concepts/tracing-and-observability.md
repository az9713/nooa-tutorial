# Tracing and Observability

Every agent method call — generation and deterministic, public and private — is traced by default as a nested OpenTelemetry span, viewable live in a local trace viewer or exported to third-party backends. This doc covers how tracing activates, what gets exported where, and the programmatic tools for analyzing traces afterward. Tracks `src/nooa/tracing/*`, `src/nooa/trace_explorer/*`, `src/nooa/viewer/*`, `src/nooa/atif/*`, `packages/nooa-cli/src/nooa_cli/commands/{start_dev,traces,import_traces,import_harbor,delete_traces}.py`.

## How tracing activates

Tracing is **automatic and additive** — no setup required for the common case, and completely silent (zero overhead beyond a reachability check) if nothing is listening. `Agent.__init__` calls `_try_auto_enable_tracing()` once per process, which attempts `enable_tracing()` and swallows `ImportError` if the tracing extra isn't installed.

`enable_tracing(exporters=None)` (`src/nooa/tracing/__init__.py`):

- **Zero-config** (`enable_tracing()`, no arguments) — sends OTLP to a local viewer if one is reachable (default `http://localhost:5001`), falling back to JSONL files on disk if not.
- **Explicit exporters** — `enable_tracing(exporters=[exporters.jsonl("./traces"), exporters.langfuse()])` sends to multiple destinations at once.

Exporter factories (`src/nooa/tracing/exporters.py`), each a pure function returning a `SpanExporter`:

| Factory | Destination | Notes |
|---|---|---|
| `exporters.jsonl(trace_dir=None)` | Local file, OTLP JSON `TracesData` objects, one per line, `{trace_dir}/{session_id}.jsonl` | `trace_dir=None` auto-detects via `TRACE_DIR` env var, else `./traces/` |
| `exporters.otlp(endpoint, headers=None)` | Any OTLP HTTP collector (Jaeger, Tempo, Phoenix, ...) | Requires `opentelemetry-exporter-otlp-proto-http` (raises `ImportError` with install instructions if missing) |
| `exporters.langfuse(host=None, public_key=None, secret_key=None)` | Langfuse, pre-configured OTLP | Falls back to `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` env vars |

Setting the `OTLP_ENDPOINT` env var also redirects where zero-config tracing sends spans, without changing any code (`examples/quickstart/06_tracing.py`). See `examples/advanced/tracing_langfuse.py`, `tracing_otlp.py`, `tracing_phoenix.py` for complete wiring examples per backend.

### Span model

Spans follow the Python call graph, not a flattened chat transcript — an orchestrator method shows up as a parent span, and every generation method or deterministic helper it calls (public, private, or dunder) shows up as a nested child span, with the same nesting for CodeAct's internal `execute_python()` calls. Because this mirrors ordinary function-call nesting, debugging an agent's trace reads like debugging a program's call stack, not like reading a raw transcript.

- **`@no_trace`** — exclude a specific method from tracing (still executes normally, generation still works if applicable) — useful for high-frequency internal helpers that would otherwise clutter a trace.
- Secret scrubbing (`src/nooa/tracing/_secret_scrubber.py`) — sensitive values are redacted before spans are exported.
- Span/trace ID generation uses a private RNG instance (`_IsolatedIdGenerator`, decoupled from the process-global `random` module) specifically so that user code calling `random.seed(...)` inside `execute_python` cells — common in simulations or reproducible demos — can't cause two separate executions to be assigned colliding span IDs.
- `src/nooa/tracing/_litellm_patch.py` / `_litellm_journal.py` instrument LiteLLM calls directly so every LLM round-trip (prompt, response, token usage) is captured without each strategy having to instrument itself.

## The trace viewer (`nooa start-dev`)

A local FastAPI app (`src/nooa/viewer/main.py`) for interactively browsing traces, part of the `nooa-cli` package (`viewer` extra: `fastapi`, `uvicorn`, `python-dotenv`, `python-multipart`).

```bash
uv run nooa start-dev            # http://localhost:5001
uv run nooa start-dev --port 5002
```

If a process is already bound to the target port, `start-dev` looks up the PID holding it (`lsof`/`ss`) to help you decide whether to kill it or pick a different port. Route groups (`src/nooa/viewer/*_routes.py`): trace viewing/ingestion (`trace_routes.py`, receives OTLP over HTTP — this is what zero-config `enable_tracing()` talks to), a programmatic trace-exploration API (`explorer_routes.py`), human annotation of runs (`annotation_routes.py`), eval-pipeline result browsing (`eval_routes.py`), and memory-subsystem browsing (`memory_routes.py`, for `nooa-memory`-equipped agents). `/v1/traces`, `/api/trace`, and `/api/refresh` are filtered out of the access log by default since the viewer polls them constantly.

If the viewer isn't running when `enable_tracing()`'s reachability check runs, tracing silently falls back to JSONL — nothing errors, nothing blocks.

## Programmatic trace analysis (`TraceExplorer`)

For querying traces from code rather than clicking through a UI — `src/nooa/trace_explorer/`, also installed as the standalone `trace-explorer` console script (`[project.scripts]` in root `pyproject.toml`):

```python
from nooa.trace_explorer import TraceExplorer

trace = await TraceExplorer.from_file("path/to/trace.jsonl")
print(await trace.help())
print(await trace.get_overview())
```

The library exposes typed accessors for common trace-analysis needs: `AgentSession`, `LLMTurn`, `ExecutionTurn`, `LLMMessage`, `ToolCall`/`ToolDefinition`, `SessionData`/`SessionSummary`, `TimelineData`/`TimelineEvent`, `OverviewData`/`OverviewStats`, `SearchResult`/`SearchMatches`, plus eval-specific types (`EvalContextData`, `ScoreDetail`) for pipelines that score agent runs. `TraceExplorerClient` is a thin client variant for talking to a running viewer instance instead of a local file. `set_quiet_mode()`/`get_quiet_mode()` control console-output verbosity for scripted use.

## CLI trace management (`nooa traces`, `nooa import-*`)

Beyond `start-dev`, the `nooa-cli` package ships trace file management commands (`packages/nooa-cli/src/nooa_cli/commands/`): `traces.py` (inspect/browse trace files), `import_traces.py` (import external OTLP traces), `import_harbor.py` (import Harbor benchmark results — see [`concepts/execution-and-storage.md`](execution-and-storage.md) for `nooa-bench`), `delete_traces.py` (cleanup). Full flag reference: [`reference/cli-reference.md`](../reference/cli-reference.md).

## ATIF — Agent Trajectory Interchange Format

`src/nooa/atif/` exports a full agent run as a **Trajectory** — a versioned (`SCHEMA_VERSION`, currently v1.7), Pydantic-defined schema (`AgentSchema`, `StepObject`, `ToolCallSchema`, `ObservationSchema`/`ObservationResultSchema`, `MetricsSchema`/`FinalMetricsSchema`, `ContentPart`, `ImageSource`, `SubagentTrajectoryRef`) intended for interchange with downstream tooling (evaluation dashboards, external uploaders) rather than as NOOA's own primary trace format. It's event-driven and decoupled from OpenTelemetry — activated separately from `enable_tracing()` via `install_atif()` or the `atif_scope()` context manager on an `EventManager`. See `examples/quickstart/14_atif_trajectory.py`.

## Related

- [`concepts/agents-and-generation-methods.md`](agents-and-generation-methods.md) — the call path every span traces.
- [`concepts/visibility-and-context.md`](visibility-and-context.md) — the hook infrastructure (`call_before_hook`/`call_after_hook`) tracing shares with middleware.
- [`guides/trace-and-debug-a-run.md`](../guides/trace-and-debug-a-run.md) — task-oriented walkthrough.
- `skills/nooa-capturing-traces/SKILL.md`, `skills/nooa-trace-viewer/SKILL.md`, `skills/nooa-trace-explorer/SKILL.md` in the repo — coding-agent-facing references.
