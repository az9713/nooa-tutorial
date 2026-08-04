# HANDOFF — resume point for the NOOA study (`~/Downloads/nooa_nvidia/labs-OO-Agents`)

**Read this first each new session.** There is no `CLAUDE.md` in this folder; the standing
conventions are the global ones in `~/.claude/CLAUDE.md` (ponytail default, plain-language
explanations). This file is the live "what to do next."

This folder is a **study of a third-party framework**. It is now also a published tutorial clone
of it — see "Git topology", which is the one thing to get right before touching anything.

## Current state (as of 2026-08-04)

**Everything is committed and pushed. Working tree clean.** Local `main` = `tutorial/main` =
`1617f05`.

- **Git topology (read before any push).** Two remotes:
  - `origin` → `https://github.com/NVIDIA-NeMo/labs-OO-Agents.git`, **push URL set to `no_push`**.
    A `git push origin` errors out by design. Never push upstream.
  - `tutorial` → `https://github.com/az9713/nooa-tutorial.git` — our public clone. `main` tracks
    `tutorial/main`. This is where work goes.
  - Base commit is upstream `0cccda1`; everything after it is ours and purely additive.
- **GitHub Pages is live** — serves `main:/docs` at `https://az9713.github.io/nooa-tutorial/`.
  `docs/.nojekyll` exists so HTML is served verbatim (without it the first two builds errored).
  Deploys via the `pages build and deployment` Action on every push to `main`.
- **README** carries a tutorial-clone notice at the very top (not affiliated with NVIDIA, links
  upstream) and a table of rendered doc links. Add a row there when a new `docs/*.html` lands.
- **Project 03 — golden-trajectory regression harness — is done** (`packages/nooa-bench/`, 11 files):
  - `src/nooa_bench/trajectory.py` (419) — `capture` / `normalize` / `shape` / `diff` / `render` / `check`
  - `src/nooa_bench/recording.py` (190) — `RecordingLLM`, strict replay, model-name carry-forward
  - `tests/conftest.py` (135) — `golden_trajectory` fixture + `--golden-update`
  - `tests/golden_agents.py` (101) — fixture agents, namespace deliberately small (see gotchas)
  - `tests/test_trajectory.py` (314), `test_recording.py` (126), `test_golden.py` (34),
    `test_live_ollama.py` (185), `tests/golden/*.json` (3 committed goldens)
  - **Verified 2026-08-03:** 53 frozen tests pass, 4 live tests pass against real Ollama, live
    suite skips cleanly with no endpoint, full repo suite passes (6,417; the 4 MCP collection
    errors are pre-existing — uninstalled `mcp` extra), ruff clean, goldens byte-stable.
  - **Not wired into CI.** Plan phase 6 is unbuilt: no workflow file runs these on push.
- **Docs** (`docs/`, all published):
  - `nooa-project-ideas.html` (56 KB) — seven projects, ranking, rubric.
  - `nooa-project-03-plan.html` (66 KB) — implementation plan, revised twice after building it.
    15 `WAS` callouts marking every claim that turned out wrong. Read "What building it changed"
    and "The live run" before touching the harness.
  - `nooa-project-03-explained.html` — line-by-line explainer of the harness, written 2026-08-04
    (`1617f05`). Layered: plain-language boxes + exhaustive code walkthrough of every new file.
  - 21 markdown files (concepts/guides/architecture) — source-grounded, **never validated by
    execution**.

## Next task

**Project 01 — portfolio analyst over live objects.** Ranked #2 by value (3.95) but the only
project scoring 5 on feature centrality, and the ideas doc's build order is `01 → 03`; 03 is done,
so 01 is next under either ordering. Spec: `docs/nooa-project-ideas.html`, project 01 block.

The shape: an `Agent` subclass holding a real `DataFrame`, broker and price feed as typed fields;
deterministic methods with real bodies (`max_position_pct()`) alongside generated methods with `...`
bodies (`propose_rebalance()`); a `MethodPrecondition` rejecting orders over the position cap so the
model is told *why* and retries instead of the run dying. The showcase is feature D — live objects
passed by reference into the REPL, so the model writes pandas against the frame that already exists
in memory rather than against a tool schema someone had to anticipate.

**Four things must be settled before or during the build — the user has not decided them yet:**

1. **A model.** Frozen replay needs one live recording. Either Ollama (see gotchas for the WSL
   gateway recipe; CodeAct needs `drop_params`) or an API key in the env. Without one, only the
   deterministic half is testable and no trajectory is ever recorded — which guts the demo.
2. **WSL.** This repo cannot run natively on Windows (see gotchas). Confirm the WSL path works
   *before* starting, not three phases in.
3. **Sandboxing.** This project runs model-generated code. NOOA's AST checks are explicitly not a
   containment boundary; OS-level isolation is required. Synthetic read-only data sidesteps it.
4. **Data.** Default to a seeded synthetic portfolio unless the user says otherwise.

Recommended split: build the full artifact against synthetic data with a stubbed model
autonomously, then one short live session to record goldens and finish the writeup with real
traces. Project 03's own history is the argument — written from a source read, wrong in eight
places, and the live run then found two more bugs no stubbed test could reach. Expect the same.

Parallel/backup tracks if 01 blocks:
- **Wire project 03 into CI** (plan phase 6). A few lines; would gate pushes on the 53 frozen tests.
- **Report bug 2 upstream** (see below) — the one finding useful to people other than us.
- **Verify `docs/` against a real run.** The quickstart's 7 steps and every CLI command were
  transcribed from source and never executed. Acceptance: quickstart runs clean from a fresh
  `uv sync --group dev`, trace viewer on `:5001`. Sandbox first.
- If the user asks for something else, that takes precedence.

## Known-open issues in the harness

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
- **`cost_usd` has never been observed varying** and `token_tolerance` has never absorbed real
  noise — two live runs gave *identical* token counts. Both are scrubbed/banded on reasoning, not
  measurement. A paid provider or a larger model at higher temperature settles it.

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
  `MethodPostcondition` + `InvariantError` in `src/nooa/strategy_validation.py`. **Directly relevant
  to project 01** — the position-cap check must be a precondition, not a `hidden` field.
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

All of these lived in session scratchpads and are **gone**. Each is a few dozen lines; the durable
record is the harness itself plus the HTML docs.

- **Variance spike** (`spike_variance.py`) — ran the same stubbed agent twice, dumped both ATIF
  trajectories as sorted JSON, diffed with `difflib`. Produced the volatile-field list.
  **Rebuild it as a pytest test, not a script** — running it as a script is exactly why it missed
  the memory-address leak (different module namespace ⇒ different prompt). See the plan's phase 1.
- **Live exploration** (`live_ollama.py`, `live_diag.py`, `codeact_ollama.py`) — superseded by the
  committed `tests/test_live_ollama.py`. Nothing in them is worth keeping.
- **HTML anchor checker** — one-liner, run after any edit touching headings or nav in a `docs/*.html`:
  ```bash
  python -c "
  import re,sys
  h=open(sys.argv[1],encoding='utf-8').read()
  ids=set(re.findall(r'id=\"([^\"]+)\"',h)); hrefs=re.findall(r'href=\"#([^\"]+)\"',h)
  print('links:',len(hrefs),'| broken:',sorted({a for a in hrefs if a not in ids}) or 'none')" docs/nooa-project-03-plan.html
  ```

## How to work here

- **Ponytail full is the default** (global `~/.claude/CLAUDE.md`): minimal diff, stdlib first, YAGNI,
  shortest explanation. Give a recommendation, not an option survey.
- **Verify by observing effects, never from a clean exit.** The biggest bug of the 03 build —
  frozen mode's replay never matching its own recording — was invisible to five green tests, because
  every one of them stubbed the thing that was broken. Run the real thing. For Pages, `curl -o
  /dev/null -w "%{http_code}"` the published URL; the legacy `/pages/builds` API lies when the
  Actions-based deploy is what actually ran.
- **Push to `tutorial`, never to `origin`.** Upstream is read-only. The push URL guard makes an
  accidental `git push origin` fail, but do not rely on it.
- **New `docs/*.html` needs a README table row** or nobody will find it.
