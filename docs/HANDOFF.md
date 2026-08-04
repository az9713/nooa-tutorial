# HANDOFF — resume point for the NOOA study (`~/Downloads/nooa_nvidia`)

**Read this first each new session.** There is no `CLAUDE.md` in this folder; the standing
conventions are the global ones in `~/.claude/CLAUDE.md` (ponytail default, plain-language
explanations). This file is the live "what to do next."

This folder is a **study of a third-party framework**, not a project of ours. That single fact
still drives most of the decisions below.

## Current state (as of 2026-08-03)

**Nothing is committed, and the amount of uncommitted work has grown a lot. See "The open
decision" — it is now urgent rather than tidy-up.**

- `labs-OO-Agents/` — clone of `https://github.com/NVIDIA-NeMo/labs-OO-Agents.git`. **Not a fork.**
  Local `main` exactly in sync with `origin/main` (`0 0`), HEAD `0cccda1`, **zero tracked files
  modified**. Everything added this session is untracked and purely additive.
- `labs-OO-Agents/docs/` — 21 untracked markdown files, ~183 KB (earlier session). Source-grounded,
  **never validated by execution**.
- `labs-OO-Agents/packages/nooa-bench/` — **11 untracked files, the golden-trajectory regression
  harness (project 03). Built and working this session.**
  - `src/nooa_bench/trajectory.py` (419) — `capture` / `normalize` / `shape` / `diff` / `render` / `check`
  - `src/nooa_bench/recording.py` (190) — `RecordingLLM`, strict replay, model-name carry-forward
  - `tests/conftest.py` (135) — `golden_trajectory` fixture + `--golden-update`
  - `tests/golden_agents.py` (101) — fixture agents, namespace deliberately small (see gotchas)
  - `tests/test_trajectory.py` (314), `test_recording.py` (126), `test_golden.py` (34),
    `test_live_ollama.py` (185), `tests/golden/*.json` (3 committed goldens)
  - **Verified:** 53 frozen tests pass, 4 live tests pass against real Ollama, live suite skips
    cleanly with no endpoint, full repo suite passes (6,417; the 4 MCP collection errors are
    pre-existing — uninstalled `mcp` extra), ruff check + format clean, goldens byte-stable.
- `nooa-project-ideas.html` (56 KB) — seven projects, ranking, rubric. Unchanged.
- `nooa-project-03-plan.html` (66 KB) — **the implementation plan, revised twice after building it.**
  15 `WAS` callouts marking every claim that turned out wrong, with originals preserved. Read the
  "What building it changed" and "The live run" sections before touching the harness.
- `NVIDIA-labs OO Agents ...-with-annotations.pdf`, `.ignore/` — pre-existing, untouched.

## The open decision (resolve this before anything else)

**32 untracked files now sit in a clone of someone else's repo, on `main`.** A `git clean -fd`
destroys the docs set *and* a working harness. Options unchanged from before:

1. **Leave untracked** — zero work, maximum risk. No longer the sane default.
2. **Commit locally on a branch** — `git -C labs-OO-Agents checkout -b feat/golden-trajectories &&
   git add docs packages/nooa-bench && git commit`. Cheapest way to stop losing work while deferring
   the real question. **Recommended.**
3. **Fork and push** — needed to share or upstream. Requires your own fork + re-pointed remote.
   A push to the current `origin` will fail.
4. **Move it out** — relocate to this folder root if it is a personal artifact.

I did not choose for you.

## Next task

Pick one:

- **Resolve the open decision above.** Option 2 is 30 seconds and removes the only real risk here.
- **Report bug 2 upstream** (see "Known-open issues"). It contradicts a documented claim of the
  framework and is the one finding useful to people other than you.
- **Widen the live run.** Everything live was verified on one provider, one model
  (`qwen2.5:1.5b`), two agent shapes. `cost_usd` has still never been observed varying and
  `token_tolerance` has never absorbed real noise — two live runs gave *identical* token counts.
  A paid provider or a larger model at higher temperature settles both.
- **Verify `docs/` against a real run** — the original next task, still undone. The quickstart's
  7 steps and every CLI command were transcribed from source and never executed.
  Acceptance: quickstart runs clean from a fresh `uv sync --group dev`, trace viewer on `:5001`.
  **Sandbox first** — NOOA executes model-generated code; its README (lines 130–133) calls its AST
  checks "defense-in-depth guardrails, not a containment boundary".
- If you ask for something else, that takes precedence.

## Known-open issues in the harness (5 of 5 of my own bugs are fixed; these two are not)

- **Bug 2 — `parallel_tool_calls` breaks CodeAct on Ollama. Worked around in tests only.**
  `litellm.UnsupportedParamsError: ollama_chat does not support parameters: ['parallel_tool_calls']`.
  `drop_params` appears 5× in `tests/`, **0× in `src/`** — deliberately, since it is global mutable
  state on `litellm` and belongs to the caller. Consequence: anyone using `nooa-bench` against
  Ollama with CodeAct still hits this. Not our bug (NOOA ↔ LiteLLM ↔ Ollama), but it contradicts
  the ideas doc's "local models are first-class... with no API key" — true for generation, false
  for CodeAct. **Not reported upstream.**
- **Skip-based flakiness handling has a ceiling.** `test_live_ollama.py` skips on `GenerationError`
  because a 1.5B model fails the CodeAct task ~1 run in 3. If the model *always* fails, the test
  skips forever while looking fine — the same rubber-stamp failure mode as stale goldens.
- **Latent, not a bug:** the record/replay round-trip is lossy in *type* — `content` goes in as a
  Pydantic model, comes back as a JSON string. Harmless today because `PredictStrategy` re-parses.
  If any strategy ever branched on `type(response.content)`, replay would silently diverge. Pinned
  by `test_structured_output_survives_the_script_round_trip`.

## Gotchas that cost real time — do not re-derive

- **This repo cannot run on Windows.** `src/nooa/storage/sqlite.py:10` imports `fcntl`. Use WSL:
  `wsl -d Ubuntu -- bash -lc 'cd /mnt/c/.../labs-OO-Agents && UV_PROJECT_ENVIRONMENT=$HOME/nooa-venv uv run --frozen pytest ...'`.
  Venv **must** live outside `/mnt/c` (9p I/O, and it collides with the half-built Windows `.venv`).
  Use `--frozen`: a plain `uv run` on Linux adds an sdist entry to `uv.lock`, dirtying a tracked file.
- **NOOA renders the defining module's namespace into the system prompt.** Adding one fixture to
  `conftest.py` broke all three goldens. That is why fixture agents live in `golden_agents.py` with a
  deliberately small namespace. Object reprs also arrive as `<function f at 0x7f3c...>`, so the
  normaliser masks hex addresses.
- **`atif_scope` always writes a file** — default `./logs/atif/`. `capture()` points it at a tempdir;
  an earlier version left ~280 JSON files in the working tree.
- **Ollama live run:** installed at `%LOCALAPPDATA%\Programs\Ollama`, model `qwen2.5:1.5b` pulled
  (986 MB). Start with `OLLAMA_HOST=0.0.0.0`; from WSL use the gateway IP from
  `ip route show default` (was `172.26.16.1`), **not** localhost. Then
  `OLLAMA_API_BASE=http://172.26.16.1:11434 uv run --frozen pytest packages/nooa-bench/tests/test_live_ollama.py -m integration`.
- **NOOA's visibility system cannot gate a method at runtime.** `src/nooa/_visible.py` is an explicit
  no-op; `hidden` is a static `Annotated[...]` marker. Runtime gating is `MethodPrecondition` /
  `MethodPostcondition` + `InvariantError` in `src/nooa/strategy_validation.py`.
- **`CodeActLiteStrategy` and `ReflexionStrategy` are experimental**, gated behind a `FutureWarning`
  via lazy re-export. Anything built on them sits on an unstable API.
- **`trace_analyzer.py` is OTel-JSONL, not ATIF.** It aggregates token counts from span files and
  knows nothing about steps or ordering. Do not plan to extend it into a trajectory differ.

## How to run the harness

```bash
# frozen (default; no key, no network)
uv run --frozen pytest packages/nooa-bench/tests            # 53 passed, 4 deselected
# re-record goldens after an intended behaviour change
uv run --frozen pytest packages/nooa-bench/tests --golden-update
# live (needs Ollama; deselected by default via the `integration` marker)
OLLAMA_API_BASE=http://172.26.16.1:11434 \
  uv run --frozen pytest packages/nooa-bench/tests/test_live_ollama.py -m integration
```

## Session-transient scratch (regenerate; durable record is the committed output)

All of these lived in the session scratchpad and are **gone**. Each is a few dozen lines; the
durable record is the harness itself plus the plan HTML.

- **Variance spike** (`spike_variance.py`) — ran the same stubbed agent twice, dumped both ATIF
  trajectories as sorted JSON, diffed with `difflib`. Produced the volatile-field list.
  **Rebuild it as a pytest test, not a script** — running it as a script is exactly why it missed
  the memory-address leak (different module namespace ⇒ different prompt). See the plan's phase 1.
- **Live exploration** (`live_ollama.py`, `live_diag.py`, `codeact_ollama.py`) — superseded by the
  committed `tests/test_live_ollama.py`. Nothing in them is worth keeping.
- **HTML anchor checker** — one-liner, run after any edit touching headings or nav:
  ```bash
  python -c "
  import re
  h=open('nooa-project-03-plan.html',encoding='utf-8').read()
  ids=set(re.findall(r'id=\"([^\"]+)\"',h)); hrefs=re.findall(r'href=\"#([^\"]+)\"',h)
  print('links:',len(hrefs),'| broken:',sorted({a for a in hrefs if a not in ids}) or 'none')"
  ```
  Currently: 15 links, 0 broken.

## How to work here

- **Ponytail full is the default** (global `~/.claude/CLAUDE.md`): minimal diff, stdlib first, YAGNI,
  shortest explanation. Give a recommendation, not an option survey.
- **Verify by observing effects, never from a clean exit.** This session's biggest bug —
  frozen mode's replay never matching its own recording — was invisible to five green tests, because
  every one of them stubbed the thing that was broken. Run the real thing.
- **Nothing here is ours to push.** Treat `labs-OO-Agents/` as read-only upstream unless the open
  decision above is resolved otherwise. Every change this session was additive; keep it that way.
