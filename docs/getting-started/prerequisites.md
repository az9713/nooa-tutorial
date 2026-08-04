# Prerequisites

Everything below is verifiable with a command — run each one before moving on to the [Quickstart](quickstart.md).

## 1. Python 3.12 or 3.13

NOOA requires Python `>=3.12,<3.14` (see `requires-python` in the root `pyproject.toml`).

```bash
python3 --version
```

Expected output: `Python 3.12.x` or `Python 3.13.x`. If you're on an older Python, install 3.12+ before continuing (NOOA relies on 3.12-era typing features).

## 2. `uv` (the only supported package manager)

The project uses [`uv`](https://docs.astral.sh/uv/getting-started/installation/) exclusively — `AGENTS.md` is explicit that pip, pip-tools, poetry, and conda are not used for development in this repo (installing the published `nooa` package with plain `pip install nooa` still works fine for consumers; it's contributing to *this repo* that assumes `uv`).

```bash
uv --version
```

Expected output: something like `uv 0.x.y`. If it's missing, follow the [official install instructions](https://docs.astral.sh/uv/getting-started/installation/) — the short version:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
```

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

## 3. An LLM provider credential

NOOA is model-agnostic via [LiteLLM](https://docs.litellm.ai/), but you need at least one working credential to run anything that actually calls a model. Set the key for whichever provider you'll use:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # for claude-* models
# or
export OPENAI_API_KEY=sk-...             # for gpt-* models
# or
export GEMINI_API_KEY=...                # for gemini/* models
```

No key is required for local providers (Ollama, vLLM) — see [`overview/what-is-this.md`](../overview/what-is-this.md) for the four-line model-selection snippet, or [`getting-started/quickstart.md`](quickstart.md) Step 1.

A template is checked in at `.env.example`:

```
# OPENAI_API_KEY=<your key>
# ANTHROPIC_API_KEY=<your key>
LITELLM_LOCAL_MODEL_COST_MAP=True
```

Copy it and fill in a real key if you'd rather use a `.env` file than shell exports:

```bash
cp .env.example .env
```

`LITELLM_LOCAL_MODEL_COST_MAP=True` tells LiteLLM to use its bundled local model-cost data instead of fetching pricing from GitHub on startup — harmless to leave set either way.

Verify a key is visible to Python:

```bash
python3 -c "import os; print('ANTHROPIC_API_KEY' in os.environ or 'OPENAI_API_KEY' in os.environ)"
```

Expected output: `True`.

## 4. Clone and sync (for working inside this repo)

If you're consuming NOOA as a dependency in your own project, skip to [`getting-started/quickstart.md`](quickstart.md) — `uv add nooa` is all you need. If you're working *inside* this repository (contributing, running the checked-in examples, running the test suite):

```bash
git clone https://github.com/NVIDIA-NeMo/labs-OO-Agents.git
cd labs-OO-Agents
uv sync --group dev
```

Expected output: a series of `Resolved`/`Installed`/`Built` lines ending without error, and a `.venv/` directory created in the repo root. This installs the core framework, the `nooa-cli`/`nooa-memory`/`nooa-bench` workspace packages, dev tooling (pytest, ruff, pyright, pre-commit), and the trace-viewer runtime, all into that `.venv`.

Verify:

```bash
uv run python -c "import nooa; print(nooa.__version__)"
```

Expected output: a version string like `0.0.6.dev12` (exact value depends on git history — see `[tool.uv-dynamic-versioning]` in `pyproject.toml`).

## 5. (Contributors only) pre-commit hooks

```bash
uv run pre-commit install
```

Expected output: `pre-commit installed at .git/hooks/pre-commit`. This wires up the license-header check, YAML/merge-conflict checks, and formatting hooks that also run in CI — see [`../CONTRIBUTING.md`](../../CONTRIBUTING.md).

## Optional, install only when you need them

| Need | Install |
|---|---|
| The `nooa` CLI + trace viewer, standalone | `uv add nooa-cli` (or `uv add "nooa[cli]"`) |
| Long-term memory (`MemoryManager`) | `uv add nooa-memory` (or `uv add "nooa[memory]"`) |
| Benchmark harness (`BenchAgent`, Harbor) | `uv add nooa-bench` (or `uv add "nooa[bench]"`) |
| MCP tool integration | `uv add "nooa[mcp]"` |
| OS-isolated execution sandbox | `uv add "nooa[sandbox]"`, plus [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) running (`openshell gateway start`) |
| Third-party tracing export (OTel/Langfuse/Phoenix) | `uv add "nooa[tracing]"` |
| NeMo Relay guardrails middleware | `uv add "nooa[nemo-relay]"` |

None of these are required for the Quickstart — only the core install and a model credential are.

Next: [`getting-started/quickstart.md`](quickstart.md).
