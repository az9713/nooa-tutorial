# Configuration Reference

> **Ownership:** this reference tracks `src/nooa/config/*.py`, `src/nooa/runtime/restrictions.py`, `src/nooa/runtime/sandbox/config.py`, and `src/nooa/layered_config.py`. Update both together — every config here is a Pydantic model; field names, types, and defaults below are copied directly from source and will drift if the source changes without this file changing too.

All in-code configs are **frozen Pydantic models** (`model_config = ConfigDict(frozen=True, ...)`) — construct a fresh instance per change, never mutate one in place. Every config with layered resolution (class-level → instance-level, or default → class → instance) implements `.merge_with(other)`, which requires `other` to be a **freshly constructed** instance (checked via `other.model_fields_set` — a config round-tripped through `model_dump()`/`model_validate()` loses the "which fields were explicitly set" information `merge_with` needs, and raises `ValueError` rather than silently merging everything).

## `ExecutionConfig`

`src/nooa/config/execution_config.py`. Class-level only: `class MyAgent(Agent, execution=ExecutionConfig(...))`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `max_nesting_depth` | `int` | `10` | Max agent-in-agent recursion depth |

## `CodeActConfig`

`src/nooa/config/strategy_config.py`. Passed to `CodeActStrategy(config=CodeActConfig(...))`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `max_iterations` | `int \| None` | `None` (unbounded) | Cap on REPL turns |
| `max_retries` | `int` | `3` | Validation-failure retries |
| `max_consecutive_text_only` | `int` | `3` | Consecutive text-only (no tool call) turns before abort; `0` disables the guard |
| `text_only_stop_behavior` | `"return_result" \| "synthetic_comment"` | `"return_result"` | How a text-only `finish_reason="stop"` response is handled — routed through `return_result()` validation (recommended), or converted to a no-op comment |
| `cell_timeout` | `float \| None` | `None` | Per-cell execution timeout, seconds |
| `max_tokens` / `temperature` / `top_p` | various `\| None` | `None` | Sampling overrides |
| `max_tool_calls` | `int \| None` | `None` | Cap on total tool calls |
| `translate_tool_calls` | `bool` | `False` | — |
| `restrictions` | `RestrictionsConfig` | `RestrictionsConfig()` | Module/call deny-list — see below |
| `execution_backend` | `"inprocess" \| "sandbox"` | `"inprocess"` | `"sandbox"` runs cells in an isolated worker process, turns `cell_timeout` into a hard bound |
| `sandbox` | `SandboxConfig` | `SandboxConfig()` | Ignored unless `execution_backend="sandbox"` — see below |
| `preconditions` | `Sequence[MethodPrecondition]` | `()` | Deterministic checks run before generation |
| `postconditions` | `Sequence[MethodPostcondition]` | `()` | Deterministic checks run after return-type validation, raise `InvariantError` for a model-correctable retry |
| `prefill` | `Prefill \| None` | `InspectInputsPrefill()` | Synthetic first-turn setup; `None` disables prefill entirely (pre-ellipsis code between the docstring and `...` still runs regardless) |

`Prefill` is a one-method protocol: `def get_code(self, call, config=None) -> str | None`. Returning a source string runs it as a synthetic prefill step; `None` skips it. To override the *strategy prompt* text specifically, use `@strategy(CodeActStrategy(), ScopedContext(context={"strategy_prompt": "Custom instructions."}))` rather than a custom `Prefill` — the decorator-context phase runs after strategy overrides and wins.

## `PredictConfig`

`src/nooa/config/strategy_config.py`. Passed to `PredictStrategy(config=PredictConfig(...))`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `preconditions` / `postconditions` | `Sequence[...]` | `()` | Same mechanism as `CodeActConfig` |
| `max_retries` | `int` | `10` | Validation-failure retries (note: higher default than CodeAct's `3`, since Predict has no iteration to fall back on) |
| `max_tokens` / `temperature` / `top_p` | various `\| None` | `None` | Sampling overrides |
| `max_error_chars` | `int` | `1000` | Truncation of the validation-error text fed back to the model on retry |
| `max_param_chars` | `int \| None` | `200_000` | Parameter-size guard; `None` disables it |
| `output_serialization` | `"event" \| "tool_call"` | `"event"` | How Predict's output is recorded in conversation history — a raw assistant-message event, or a synthetic `return_result()` tool-call event (clearer for downstream tool-using models reading this history) |

## `ReflexionConfig`

`src/nooa/config/strategy_config.py`. For the **experimental** `ReflexionStrategy` — see `src/nooa/strategies/reflexion.py` for current fields; not reproduced here since the strategy itself is not recommended for new code (see [`concepts/strategies.md`](../concepts/strategies.md)).

## `RestrictionsConfig`

`src/nooa/runtime/restrictions.py`. **Guardrails, not a security boundary** — see [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md) before relying on this for anything adversarial.

| Field/function | Meaning |
|---|---|
| `DEFAULT_BLOCKED_MODULES` | Frozenset stripped entirely from `exec_globals` — `subprocess`, `socket`, `http.client`, `urllib.request`, `ftplib`, and similar modules with no legitimate async use inside CodeAct |
| `restricted_imports` field on `RestrictionsConfig` | A configurable deny-list, separate from the always-blocked set above |
| `set_restricted_imports(modules: frozenset[str] \| None)` | Process-global override applied to every `RestrictionsConfig()` constructed afterward; `frozenset()` allows everything, `None` clears the override |
| `get_restricted_imports()` | Read the current process-global override |

## `SandboxConfig`

`src/nooa/runtime/sandbox/config.py`. Ignored unless `CodeActConfig.execution_backend == "sandbox"`. Default posture is safe/minimal: filesystem confined, network off, memory/CPU caps opt-in.

| Field | Type | Default | Kernel mechanism | Meaning |
|---|---|---|---|---|
| `filesystem` | `bool` | `True` | Landlock | Enforce default-deny filesystem confinement |
| `workspace` | `str \| None` | `None` | Landlock | A directory the cell gets read+write access to; `None` = no writable directory |
| `allow` | `tuple[FileRule, ...]` | `()` | Landlock | Explicit additional filesystem allow rules (`FileRule(path=..., access="read" \| "read_write")`) |
| `max_memory_mb` | `int` | `0` (disabled) | `RLIMIT_AS` | Memory cap |
| `max_cpu_seconds` | `int` | `0` (disabled) | `RLIMIT_CPU` | CPU cap |
| `network` | `bool` | `False` | seccomp `socket()` | Whether network access is allowed |

`cell_timeout` (from `CodeActConfig`) supplies the sandbox's hard-kill timeout — there's no separate sandbox-specific timeout field.

## `TruncationConfig` and sub-configs

`src/nooa/config/truncation_config.py`. Two layers: whole-context token budgets (top-level fields) and per-mechanism sub-configs. Resolved per-agent via default → class-level (`class MyAgent(Agent, truncation=...)`) → instance-level (`MyAgent(truncation=...)`) merge, and per-method via `@strategy(..., truncation=...)`.

**Top-level `TruncationConfig` fields:**

| Field | Type | Default | Meaning |
|---|---|---|---|
| `max_context_tokens` | `int \| None` | `None` | Total context token budget |
| `max_event_tokens` | `int \| None` | `None` | Total event token budget |
| `min_preserved_events` | `int` | `5` | Minimum recent events always preserved during L4 eviction, so the model always sees its current task + recent reasoning |
| (output-token planning reserve field) | `int` | see source | Shrinks the usable context window for the default context-block budget, the "ctx N%" utilization warning, and post-error archive sizing; `0` disables both the reserve and the auto-derived default budget |
| `capture` | `CaptureConfig` | see below | Head/tail truncation of raw stdout/stderr/error text |
| `media_capture` | `MediaCaptureConfig` | see below | Cap on multimodal content blocks captured by `show()` |
| `event_format` | `FormatConfig` | see below | Rendering defaults for event fields at trajectory-build time (renders every turn — needs to be generous) |
| `prefill_format` | `FormatConfig` | see below | Rendering defaults for parameter rendering at method invocation (one-shot per call — tighter defaults are fine) |
| `context_block_format` | `FormatConfig` | see below | Rendering defaults for non-string `self.context[key] = value` assignments (few blocks per agent, often intentionally large, e.g. `doc(self)`) |

**`CaptureConfig`** (char budgets for `TruncatingStringIO`-captured streams):

| Field | Default | Meaning |
|---|---|---|
| `max_stdout` | `50_000` | Max chars of stdout per cell |
| `max_stderr` | `2_000` | Max chars of stderr per cell |
| `max_error` | `10_000` | Max chars of error/traceback per cell |
| `tail` | `None` (= 50/50 head/tail split) | Chars reserved for the tail window in head/tail truncation |
| `file_backed` | `False` | When `True`, uses `FileBackedTruncatingStringIO` — streams full output to a temp file on disk while still truncating the in-memory representation; the temp file path is included in the truncation notice |

Validated: all three `max_*` fields must be `> 0`; `tail`, if set, must be `>= 0` and strictly less than each corresponding `max_*` field.

**`MediaCaptureConfig`**:

| Field | Default | Meaning |
|---|---|---|
| `max_attachments_per_execution` | `5` | Max media attachments `show()` can capture **per `execute_python` cell** (not per turn or per run — a single turn issuing multiple cells can attach up to this many *each*). Once reached, further `show()` calls in that cell are dropped and `[show() limit reached (N), attachment not added]` prints to stdout so the model can see the spillover. |

**`FormatConfig`** (recursive bounds for `pformat`-based rendering; field names match `pformat()` kwargs exactly):

| Field | Default | Meaning |
|---|---|---|
| `max_string` | `500` | Max chars per string before a `str(len=N, [:H], [-T:])` marker |
| `max_length` | `50` | Max items per container before a `type(len=N, [:H], [-T:])` marker |
| `max_depth` | `4` | Max nesting depth |

A per-field `Annotated[T, spec(max_string=N, ...)]` annotation overrides these defaults for that single field.

## `TokenBudgetConfig` / `MethodSummarizerConfig`

`src/nooa/config/summarizer_config.py`.

**`TokenBudgetConfig`** (for `TokenBudgetSummarizer.install(agent, config=...)`):

| Field | Default |
|---|---|
| `max_tokens` | `100_000` |
| `preserve_recent` | `10` |
| `target_chars` | `1000` |

**`MethodSummarizerConfig`** (for `MethodSummarizer.install(agent, config=...)`):

| Field | Default |
|---|---|
| `min_events` | `3` |
| `exclude_root` | `True` |
| `target_chars` | `1000` |

## `ModelConfig`

`src/nooa/config/model_config.py`. The typed boundary over one `llm_config.yaml` model-alias entry (`extra="allow"` — any litellm passthrough key stays accessible as an attribute even if not explicitly typed here).

| Field | Type | Meaning |
|---|---|---|
| `model_name` | `str \| None` | The litellm model string actually sent to the provider; falls back to the alias name itself if omitted |
| `api_base` | `str \| None` | Custom API base URL |
| `api_key_env` | `str \| None` | Name of the env var holding the API key — **not the key itself** |
| `client_type` | `str \| None` | — |
| `context_window` | `int \| None` | — |
| `max_tokens` / `temperature` / `top_p` | various `\| None` | Sampling defaults for this alias |

Build one via `ModelConfig.from_registry(name, raw_dict)`, or get a fully resolved view via `nooa.config.get_model_config()` / `nooa.config.resolved_config()` (the programmatic equivalent of `nooa config show`).

## Layered YAML config files

Three files, same resolution mechanism (`nooa.layered_config`, precedence last-wins): `llm_config.yaml`, `settings.yaml`, `secrets.yaml`.

1. **Bundled defaults** — every package registered under the `nooa.bundled_configs` entry-point group (e.g. `nemo-oo-agents-nvidia` for NVIDIA-gateway model aliases).
2. **User config** — `~/.config/nooa/llm_config.yaml` (base dir overridable via `NEMO_OO_USER_DIR`).
3. **Project-local config** — `.nooa/llm_config.yaml` in the current project.
4. **`NEMO_OO_LLM_CONFIG` env var** — comma-separated YAML paths, highest priority.

Inspect the resolved result with `nooa config show` (secrets redacted to key names only), find the user-level path with `nooa config path`, and copy bundled defaults to the user-level path for local editing with `nooa config eject`. See [`reference/cli-reference.md`](cli-reference.md#nooa-config).

## Environment variables

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / etc. | LLM provider credentials, per LiteLLM's own conventions |
| `LITELLM_LOCAL_MODEL_COST_MAP` | `True` uses LiteLLM's bundled local model-cost data instead of fetching pricing from GitHub on startup |
| `TRACE_DIR` | Where zero-config JSONL trace export writes, when no explicit `exporters.jsonl(trace_dir=...)` is given |
| `OTLP_ENDPOINT` | Redirects zero-config tracing's OTLP destination away from the default local viewer |
| `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Used by `exporters.langfuse()` when the corresponding arguments aren't passed explicitly |
| `NEMO_OO_USER_DIR` | Overrides the base directory for user-level layered config |
| `NEMO_OO_LLM_CONFIG` | Comma-separated YAML paths, highest-priority layer in LLM config resolution |

## Related

- [`concepts/strategies.md`](../concepts/strategies.md) — `CodeActConfig`/`PredictConfig` in context.
- [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md) — `RestrictionsConfig`/`SandboxConfig` in context.
- [`concepts/visibility-and-context.md`](../concepts/visibility-and-context.md) — `TruncationConfig`'s effect on what the model sees.
- `skills/nooa-codeact-advanced/SKILL.md` in the repo — truncation/restriction tuning walkthroughs.
