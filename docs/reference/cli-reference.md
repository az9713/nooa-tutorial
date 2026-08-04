# CLI Reference: `nooa`

> **Ownership:** this reference tracks `packages/nooa-cli/src/nooa_cli/commands/*.py` and `packages/nooa-cli/src/nooa_cli/__init__.py`. Update both together — commands are auto-discovered from that directory (see below), so a new command file needs a matching entry here.

Install: `uv add nooa-cli` (or `uv add "nooa[cli]"`, or it's already present after `uv sync --group dev` inside this repo). Data-science libraries pre-loaded into the LLM REPL: `uv add "nooa-cli[datascience]"`.

```bash
nooa --help
```

## How commands are discovered

Every non-underscore-prefixed `.py` file in `packages/nooa-cli/src/nooa_cli/commands/` that exports a module-level `command` (a `click.Command` or `click.Group`) is automatically registered as a `nooa <filename-with-dashes>` subcommand — `commands/start_dev.py` becomes `nooa start-dev`, unless the module sets `NAME = "..."` to override it. External packages can contribute additional top-level subcommands via the `nooa_cli.commands` entry-point group in their own `pyproject.toml`; built-in commands always win name collisions (a plugin trying to shadow `eval`/`config`/etc. is logged and skipped), and a broken plugin is skipped with a warning rather than breaking `nooa` entirely.

## `nooa start-dev`

Starts the local trace viewer (FastAPI + uvicorn).

```bash
nooa start-dev                  # http://localhost:5001
nooa start-dev --port 5002      # custom port
```

If another process already holds the target port, `start-dev` looks up its PID (via `lsof` on macOS/most Linux, or `ss` as a fallback) and reports it so you can decide whether to stop it or use a different port. Requests to `/v1/traces`, `/api/trace`, and `/api/refresh` are excluded from the access log (the viewer polls these constantly). See [`concepts/tracing-and-observability.md`](../concepts/tracing-and-observability.md).

## `nooa traces`

Manage trace and evaluation files on disk.

```bash
nooa traces list                    # list discovered trace directories
nooa traces stats                   # show trace file statistics (count, size)
nooa traces delete                  # delete, with confirmation prompt
nooa traces delete -n               # dry run — show what would be deleted, delete nothing
nooa traces delete --older-than 7   # only delete files older than 7 days
```

Trace-directory discovery is bounded (not a recursive filesystem scan) to locations NOOA itself can write: the project trace directory used by `--trace` flags, the legacy `./traces` convention at the project root, and an explicit `$TRACE_DIR` override when set. Directories like `.venv`, `node_modules`, `.git`, `__pycache__` are always excluded from scanning.

## `nooa import-traces`

Import external OTLP trace files into the local viewer's storage for browsing. See `packages/nooa-cli/src/nooa_cli/commands/import_traces.py` for exact flags (run `nooa import-traces --help`).

## `nooa import-harbor`

Import [Harbor](https://github.com) benchmark run results (from `nooa-bench`'s `nemo-harbor` runner) into the trace viewer, so benchmark runs are browsable the same way live-agent traces are. See `packages/nooa-cli/src/nooa_cli/commands/import_harbor.py` (run `nooa import-harbor --help`).

## `nooa delete-traces`

Standalone deletion entry point (also reachable via `nooa traces delete` — see `commands/delete_traces.py` / `commands/traces.py` for the precise relationship between the two in your installed version). Prefer `nooa traces delete` for the documented flag surface above.

## `nooa eval`

Thin passthrough to `python -m eval_pipeline` — every argument is forwarded as-is, so this command's flag surface always matches `eval_pipeline`'s own CLI rather than being redefined here (`context_settings={"ignore_unknown_options": True, "allow_extra_args": True}`).

```bash
nooa eval --config config.yaml
nooa eval --config config.yaml --runs 3 --parallel 10
nooa eval --config config.yaml --test sentiment --limit 5
nooa eval --config config.yaml --models gpt-4,claude-3 -q
nooa eval --config config.yaml --default_strategy codeact
nooa eval --help                                          # forwarded to eval_pipeline's own --help
```

Requires the `eval_pipeline` package, which ships as part of the monorepo workspace but is **not** a dependency of the standalone `nooa-cli` wheel — if it's missing, the command prints install guidance rather than a bare `ImportError`. Install it with:

```bash
uv add "eval_pipeline @ git+https://github.com/NVIDIA-NeMo/labs-OO-Agents.git@main#subdirectory=util/eval_pipeline"
```

See [`util/eval_pipeline/README.md`](../../util/eval_pipeline/README.md) for the pipeline itself.

## `nooa config`

Inspect and customize the layered LLM configuration.

```bash
nooa config show     # print resolved layers for llm_config.yaml / settings.yaml / secrets.yaml (secret values redacted, only key names shown)
nooa config path      # print the user-level YAML path (where `eject` writes)
nooa config eject      # copy bundled-defaults YAML to the user-level path so you can edit it locally
```

Config precedence (last wins), per `commands/config.py`'s own docstring:

1. **Bundled defaults** — from every package registered under the `nooa.bundled_configs` entry-point group (e.g. install `nemo-oo-agents-nvidia` for NVIDIA-gateway model aliases).
2. **User config** — `~/.config/nooa/llm_config.yaml` (override the base directory with `NEMO_OO_USER_DIR`).
3. **Project-local config** — `.nooa/llm_config.yaml` in the current project.
4. **`NEMO_OO_LLM_CONFIG` env var** — comma-separated YAML paths; the global override, highest priority.

All three config files (`llm_config.yaml`, `settings.yaml`, `secrets.yaml`) share this same directory structure and precedence order (`nooa.layered_config`). See [`reference/configuration-reference.md`](configuration-reference.md) for what goes in each file.

## `trace-explorer` (separate console script)

Not a `nooa` subcommand — a standalone script installed by the core `nooa` package itself (`[project.scripts]` in the root `pyproject.toml`: `trace-explorer = "nooa.trace_explorer:main"`).

```bash
trace-explorer --help
```

See [`concepts/tracing-and-observability.md`](../concepts/tracing-and-observability.md#programmatic-trace-analysis-traceexplorer) for the underlying `TraceExplorer` library this wraps.

## `nemo-harbor` (from `nooa-bench`)

Also a separate console script, shipped by the `nooa-bench` package (`uv add nooa-bench`):

```bash
nemo-harbor --help
```

Runs the Harbor benchmark harness (`BenchAgent`) used to reproduce the SWE-bench Verified / Terminal-Bench 2.0 results from the project's [paper](https://arxiv.org/abs/2607.20709). See [`concepts/execution-and-storage.md`](../concepts/execution-and-storage.md#nooa-bench--benchmarking).

## Shell completion

`packages/nooa-cli/src/nooa_cli/completion.py` provides shell completion support — run `nooa --help` on your installed version for the exact activation command for your shell, since this can vary by `click` version.

## Related

- [`getting-started/quickstart.md`](../getting-started/quickstart.md) — `nooa start-dev` in context.
- [`concepts/tracing-and-observability.md`](../concepts/tracing-and-observability.md) — what the viewer shows.
- `packages/nooa-cli/docs/activity-introspection-design.md` — design notes for the viewer's activity-introspection subsystem.
