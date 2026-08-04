# Execution Safety and State Storage

Two independent concerns that both come up whenever an agent runs generated code and needs its state to survive: what stops generated Python from doing something dangerous (and what doesn't), and how agent state — events and snapshots — gets persisted. Tracks `src/nooa/runtime/code_validator.py`, `src/nooa/runtime/restrictions.py`, `src/nooa/runtime/sandbox/*`, `src/nooa/storage/*`, `packages/nooa-bench/`, `packages/nooa-memory/`.

## The safety model: guardrails vs. containment

Read this section before running any agent that executes LLM-generated code against anything you care about.

NOOA validates generated code before running it: an AST check (`src/nooa/runtime/code_validator.py`) catches syntactic issues, and a module/call deny-list (`RestrictionsConfig`, `src/nooa/runtime/restrictions.py`) blocks importing or calling a defined set of dangerous names. **These exist to keep generated code from freezing the event loop and to catch common mistakes early — not to stop code that is actively trying to escape.** The restrictions module says this about itself, verbatim: *"These lists are guardrails, not a security boundary... A static deny-list over Python cannot [contain adversarial code]: `open()` gives arbitrary file I/O, `importlib.util`/`importlib.machinery` load modules straight from a path, and reflection reaches the rest. Extending these lists to 'close an escape' is unwinnable whack-a-mole."*

`DEFAULT_BLOCKED_MODULES` (fully stripped from `exec_globals`, since they have no legitimate async use inside CodeAct and can block the event loop) includes `subprocess`, `socket`, `http.client`, `urllib.request`, `ftplib`, and similar. This list, plus a separate `restricted_imports` set, is consumed in three places: `CodeActConfig`'s defaults, `exec_globals` stripping at cell-execution time, and `BlockingCallValidator` (which catches blocking calls even if the module itself wasn't blocked). `set_restricted_imports(modules)` / `get_restricted_imports()` let you override the process-global restriction list — e.g. `set_restricted_imports(frozenset())` to allow everything (not recommended outside a fully sandboxed environment), or pass a custom `frozenset` to tighten it further.

**The actual containment boundary is OS-level isolation.** Run any agent that executes generated code inside a container, a VM, or [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) — never rely on the in-process validators alone, no matter how comprehensive the deny-list looks. This is stated identically in the root `README.md`'s safety note and in the restrictions module's own docstring, which is a deliberate signal that it isn't a throwaway disclaimer.

### Two execution backends for `execute_python` cells

`CodeActConfig.execution_backend` (see [`concepts/strategies.md`](strategies.md)) picks between:

- **`"inprocess"`** (default) — cells run in the agent's own process and event loop. Zero behavior change from the historical implementation; fastest, but only as isolated as the validators above.
- **`"sandbox"`** — each cell runs in a locked-down **worker process**, configured by `SandboxConfig` (`src/nooa/runtime/sandbox/config.py`). This turns `cell_timeout` into a *hard*, kernel-enforced bound rather than a cooperative one, and adds independently-configurable guardrails, each backed by an irrevocable kernel mechanism:

  | Guardrail | Config field | Kernel mechanism |
  |---|---|---|
  | Timeout | reuses `CodeActConfig.cell_timeout` | parent hard-kill |
  | Memory | `max_memory_mb` | `RLIMIT_AS` |
  | CPU | `max_cpu_seconds` | `RLIMIT_CPU` |
  | Filesystem | `filesystem`, `workspace`, `allow`/`deny` (`FileRule` entries) | Landlock path rules |
  | Network | `network` | seccomp `socket()` interception |

  Default posture is the safe/minimal one: filesystem confined to read-only system paths plus an optional single read-write `workspace` directory, network off, memory/CPU caps opt-in (`0` disables them). `SandboxConfig` fields are entirely ignored unless `execution_backend == "sandbox"`.

Requires the `sandbox` extra (`uv add "nooa[sandbox]"`); using it for whole-agent isolation (not just per-cell) additionally involves running [OpenShell](https://github.com/NVIDIA/OpenShell) (`openshell gateway start`) — the framework's own framing is that this is "a wrapper, not a code change": the same agent script runs locally or isolated with identical semantics, so isolation is a deploy-time decision rather than a rewrite (`examples/README.md`).

### Async safety

`src/nooa/runtime/async_safety.py` and the blocking-call validator work together to catch a specific, easy-to-hit failure mode: generated code calling something synchronous and blocking (a blocking I/O call, a tight CPU loop with no `await`) inside the agent's single event loop, which would stall every other concurrent agent sharing that loop. This is a correctness/liveness guard, not a security one — it exists alongside, not instead of, the restrictions above.

## State storage

### Events vs. snapshots

Two distinct persistence concepts, easy to conflate:

- **Events** are the append-only history of everything that happened during a run (see [`concepts/visibility-and-context.md`](visibility-and-context.md)) — written continuously through `agent.event_manager` to whatever `EventBackend` the active `StorageManager` provides.
- **A snapshot** is a point-in-time save/restore of an agent's *state* (context blocks, method registry, attribute values) — an explicit action, not a continuous stream.

### `StorageManager` — the persistence interface

`src/nooa/storage/manager.py` defines `StorageManager` as a `Protocol` with one property and two methods:

```python
class StorageManager(Protocol):
    @property
    def event_backend(self) -> EventBackend: ...
    def save_snapshot(self, agent: Agent) -> str: ...            # returns a snapshot_id
    def restore_snapshot(self, snapshot_id: str, agent: Agent) -> None: ...
```

The agent owns its `EventManager`; storage only owns the `EventBackend` underneath it. This separation is deliberate: swapping storage (`/clear`, `/session new`, or any equivalent "start fresh" operation) preserves the agent's subscribers and middleware, registered on the stable `EventManager`, while only the persistence *target* changes underneath.

Two implementations ship with the framework:

- **`InMemoryStorageManager`** (`src/nooa/storage/in_memory.py`) — the default when no `storage=` is passed to `Agent()`. No persistence: events live only in process memory, gone when the process exits.
- **`SQLiteStorageManager`** (`src/nooa/storage/sqlite.py`) — durable event storage backed by SQLite, plus snapshot save/restore.

```python
storage = SQLiteStorageManager("agent_state.db")
agent = MyAgent(storage=storage)
# events stream automatically to storage via agent.event_manager
snapshot_id = agent.save()                    # explicit snapshot
# ... later, new process ...
agent = MyAgent.load(snapshot_id, storage=storage)
```

`src/nooa/storage/json_snapshot.py` and `snapshot.py`/`snapshot_vars.py` implement the actual serialization format snapshots use; `markers.py` defines the opt-out mechanism — `Annotated[T, nosnapshot]` on a field, or `__nosnapshot__ = True` on a class (used internally so `Agent` instances are never serialized as nested values inside another object's snapshot). Non-serializable attributes are not fatal to a snapshot: they're logged with a warning and skipped, unless explicitly marked `nosnapshot` (in which case skipping is silent and intentional). `serialization.py` centralizes the encode/decode logic both snapshot formats share.

## `nooa-memory` — long-term recall across sessions

A separate workspace package (`uv add nooa-memory`, or `uv add "nooa[memory]"`) that installs the `nemo.memory` skill, giving an agent persistent recall across sessions backed by vector search — distinct from both events (within-run history) and snapshots (point-in-time full-state save/restore). The default vector backend is numpy-only, no extra dependencies; `sqlite-vec` and `chromadb` backends are used if you install them yourself. See `examples/quickstart/12_memory.py` and `examples/arc_agi_3` for a worked usage example, and `examples/advanced/memory.py` for lower-level persistent-memory patterns.

## `nooa-bench` — benchmarking

Another workspace package (`uv add nooa-bench`) shipping `BenchAgent` and a Harbor-based benchmark runner (`nemo-harbor` console script) used to reproduce the SWE-bench Verified and Terminal-Bench 2.0 results reported in the project's [paper](https://arxiv.org/abs/2607.20709). `examples/benchmarks/` (`bench_agent.py`, `harbor_adapter.py`, `harbor_minimal.yaml`) shows a minimal harness wiring. The `nooa traces import-harbor` CLI command (see [`reference/cli-reference.md`](../reference/cli-reference.md)) imports Harbor run results into the trace viewer for inspection.

## Related

- [`concepts/strategies.md`](strategies.md) — `CodeActConfig.execution_backend`/`sandbox`/`restrictions` in the context of the strategy that uses them.
- [`overview/what-is-this.md`](../overview/what-is-this.md) — the top-level safety warning this section expands on.
- `skills/nooa-codeact-advanced/SKILL.md` in the repo — execution internals and restriction tuning, coding-agent-facing.
