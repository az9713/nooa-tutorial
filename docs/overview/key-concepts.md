# Key Concepts

Every term below appears elsewhere in this documentation without being redefined. If you hit an unfamiliar word in a guide or reference doc, it's here.

**Agent** — a Python class that subclasses `nooa.Agent`. Its fields are state, its methods are capabilities, its class docstring is the system prompt, and any method with an ellipsis (`...`) body is a generation method. Defined in `src/nooa/agent.py`.

**Generation method** — a method whose body is literally `...`. Detected at class-definition time by `nooa.ellipsis_detection.has_ellipsis_body` and wrapped by the metaclass so that calling it invokes a `GenerationStrategy` instead of running Python. Its signature and docstring form the prompt; its return type annotation is the validated contract for the LLM's output. See [`concepts/agents-and-generation-methods.md`](../concepts/agents-and-generation-methods.md).

**Orchestrator** — a method (or a whole class) with a real, non-ellipsis body that calls one or more generation methods in sequence. Pure Python control flow around LLM-driven steps. A class made entirely of orchestrator methods doesn't need to subclass `Agent` at all.

**Strategy** (`GenerationStrategy`) — the pluggable execution engine that implements *how* a generation method's task gets solved. Attached via `@strategy(...)` or inherited as the class/global default. See [`concepts/strategies.md`](../concepts/strategies.md) for the full catalogue (`PredictStrategy`, `CodeActStrategy`, `ReflexionStrategy`, `TemplateStrategy`, `CompositeStrategy`, and others).

**CodeAct** — the default strategy (`CodeActStrategy`). The LLM reasons in an iterative Jupyter-style Python REPL: it calls an `execute_python()` tool to run code (which can call other methods on `self`), observes stdout/results, and eventually calls `return_result(...)` with a value matching the method's return type. Named after the "Executable Code Actions Elicit Better LLM Agents" pattern.

**Predict** — `PredictStrategy`. A single-shot, non-iterative LLM call: the model is asked once for structured output matching the return type, validated, and retried on validation failure — no code execution, no tool loop. Best for classification/extraction where iteration isn't needed.

**`doc(obj)`** — a runtime function (progressive-disclosure documentation) that renders an object's type shape — fields, methods, signatures, docstrings — as text the LLM can read. `doc(self)` shows the agent's own API; `doc(other_obj)` lets the model discover the shape of any object it holds a reference to, even one typed as `Any`. Backed by `src/nooa/agentdoc/`.

**Visibility** — the rule set that decides what `doc()` shows the LLM and what code the LLM's generated Python can reference (`exec_globals`). Default is **visible unless hidden**: module-level names, public methods/fields on an agent, are visible; `_private` methods/fields, dunder methods, and anything under `with hidden:` or marked `@hidden` / `Annotated[T, hidden]` are not. See [`concepts/visibility-and-context.md`](../concepts/visibility-and-context.md).

**`@hidden`** — decorator/annotation marker that removes a module-level function, an agent method, or a field from what the LLM sees, regardless of the default visibility rule for its scope.

**`@spec(hidden=False)`** — the inverse: explicitly un-hides a `_private`-named method that would otherwise be hidden by the underscore convention. Also used imperatively — `spec(self, "context", hidden=False)` — to expose the always-present-but-hidden-by-default `context`/`events` APIs to the LLM.

**Context block** — a labelled piece of text pinned into the agent's system prompt, set via `self.context["key"] = value`. Rendered as an XML-ish `<key>content</key>` block. Two kinds:
  - **Static context** — a fixed value, evaluated once at assignment (`self.context["policy"] = "..."`).
  - **Dynamic context** — a Python expression re-evaluated every LLM turn (`self.context.set_dynamic("notes", "self.render_notes()")`, or `Context(expr="...")`).
  Backed by `src/nooa/context_blocks/` and exposed to the agent via `ContextApi` (`self.context`).

**`ContextApi`** — the dict-like, LLM-facing wrapper (`self.context`) over the agent's raw context-block state (`context_manager`). Always present on every agent, hidden from the LLM by default; opt in with `spec(self, "context", hidden=False)`.

**Event** — a single recorded occurrence in an agent's run: a task starting, an LLM call completing, code executing, an error, a turn boundary. Events are the append-only log the framework is built around ("event sourcing" — see `pyproject.toml`'s own description of NOOA). Backed by `src/nooa/runtime/events.py` and `src/nooa/events.py`.

**`EventsApi`** — the LLM-facing wrapper (`self.events`) for querying past events by type, tag, or text. Always present, hidden from the LLM by default; opt in with `spec(self, "events", hidden=False)`.

**`EventQuery`** — a filter specification for selecting which events feed into a prompt or a query result (e.g. "only this call's events," "only errors").

**Snapshot** — a serialized capture of an agent's state (context blocks, method registry, attribute values) that can be restored later via a `StorageManager`. Distinct from events: events are the append-only history; a snapshot is a point-in-time save/restore mechanism. Fields/classes can opt out with `Annotated[T, nosnapshot]` or `__nosnapshot__ = True`.

**`StorageManager`** — the persistence interface (`src/nooa/storage/manager.py`) an agent is constructed with. Owns the `EventBackend` (where events are written) and implements `save_snapshot()` / `restore_snapshot()`. Ships with `InMemoryStorageManager` (default, no persistence) and `SQLiteStorageManager`.

**Truncation** — the bounding of stdout/stderr/error text, pretty-printed values, and rendered event history so prompts stay within budget as a run grows. Configured via `TruncationConfig` and its sub-configs (`CaptureConfig`, `MediaCaptureConfig`, `FormatConfig`); truncated values render with a `type(len=N, ...)` marker rather than silently dropping data. See [`reference/configuration-reference.md`](../reference/configuration-reference.md).

**Summarizer** — a mechanism that compresses older event history once a budget is crossed, so long-running agents don't hit the context window. `TokenBudgetSummarizer` compresses continuously against a token budget; `MethodSummarizer` compresses per completed method call. `src/nooa/agents/summarization.py`.

**Tool (in NOOA's sense)** — there is no separate tool abstraction. Any regular method on `self`, or any object attached as a class/instance attribute (an MCP connection, a `ShellTools` instance, an external API client), is automatically callable by the LLM inside CodeAct-generated code and automatically discoverable via `doc(self)` — no decorator, no schema registration.

**Skill** (NOOA runtime sense — `nooa.Skill` / `nooa.TextSkill`) — a class attribute that injects curated context (guidelines, domain knowledge, examples) into an agent, or bundles reusable slash commands. Distinct from the repo's own `skills/*/SKILL.md` bundles, which are instructions *for coding agents* about how to author NOOA code (see next entry). See [`concepts/tools-skills-and-mcp.md`](../concepts/tools-skills-and-mcp.md).

**`SKILL.md` bundle** — a portable markdown file (with YAML frontmatter) that teaches a *coding agent* (Claude Code, Cursor, Codex) how to work with NOOA — e.g. `skills/nooa-agent-authoring/SKILL.md`. These are documentation for humans-plus-coding-agents, not something a NOOA `Agent` instance loads at runtime, though the file format is compatible with `TextSkill`.

**MCP (Model Context Protocol)** — a standard protocol for exposing external tools/services to an LLM. NOOA's `nooa.mcp.MCPManager` connects to an MCP server and exposes it as a regular `self.<name>` attribute, so MCP tools are called exactly like local methods. Requires the `mcp` extra (`uv add 'nooa[mcp]'`).

**Trace / span** — the OpenTelemetry-based observability unit. Every agent method call (generation or deterministic, public or private, unless marked `@no_trace`) becomes a span with parent-child nesting that mirrors the Python call graph. Traces are viewed live in the local **trace viewer** (`nooa start-dev`, `http://localhost:5001` by default) or exported via `enable_tracing(exporters=[...])` to JSONL, OTLP, Langfuse, or Phoenix. See [`concepts/tracing-and-observability.md`](../concepts/tracing-and-observability.md).

**Trace Explorer** — a separate library/CLI (`nooa.trace_explorer`, `trace-explorer` console script) for *programmatic* querying and analysis of captured traces, as opposed to the interactive viewer's UI.

**ATIF** — Agent Trajectory Interchange Format (`src/nooa/atif/`). An exportable, schema-defined representation of an agent's full run (its "trajectory") for interchange with other tooling/evaluation pipelines.

**Sandbox** — the isolated execution mode for `execute_python` cells. `execution_backend="sandbox"` in `CodeActConfig` runs each cell in a locked-down worker process with OS-enforced timeout/memory/CPU/filesystem/network limits, versus the default `"inprocess"` mode which runs in the agent's own event loop. Distinct from, but complementary to, running the whole agent inside [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) — see [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md).

**Cascading LLM resolution** — the order NOOA resolves which LLM client an agent uses: instance-level (`MyAgent(llm=...)`) → class hierarchy (`class MyAgent(Agent, llm=...)`, walking the MRO) → the parent agent at runtime (for agents constructed inside another agent's generated code) → error if none found. Lets you set a default once and override narrowly.

**`UnifiedLLM`** — the LiteLLM-backed client wrapper (`src/nooa/unifiedllm/`) returned by `get_llm_client(model_name, ...)`. Any [LiteLLM](https://docs.litellm.ai/)-supported model string works — Anthropic, OpenAI, Gemini, Ollama, vLLM, Bedrock, and more.

**Workspace package** — one of the separately-versioned, separately-installable distributions that live inside this repo alongside the core `nooa` package: `nooa-cli` (the `nooa` command, trace viewer runtime, eval runner), `nooa-memory` (long-term memory / vector recall), `nooa-bench` (benchmark harness, `BenchAgent`), and `eval_pipeline` (not published to PyPI). Wired together via a `uv` workspace (`[tool.uv.workspace]` in the root `pyproject.toml`).

Continue to [`getting-started/prerequisites.md`](../getting-started/prerequisites.md) to set up an environment, or [`getting-started/quickstart.md`](../getting-started/quickstart.md) to write your first agent immediately.
