# HANDOFF — resume point for the NOOA study (`~/Downloads/nooa_nvidia/labs-OO-Agents`)

**Read this first each new session.** There is no `CLAUDE.md` in this folder; the standing
conventions are the global ones in `~/.claude/CLAUDE.md` (ponytail default, plain-language
explanations). This file is the live "what to do next."

This folder is a **study of a third-party framework**. It is now also a published tutorial clone
of it — see "Git topology", which is the one thing to get right before touching anything.

## Current state (as of 2026-08-04)

**Everything is committed and pushed. Working tree clean.** Local `main` = `tutorial/main` =
`70a8a5b`.

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
- **Project 01 — portfolio analyst over live objects — code is done** (`examples/portfolio/`,
  8 files, `2874660` + `70a8a5b`). Deliberately *not* a package: no `pyproject.toml`, no uv
  workspace member, no `uv.lock` churn. One line added to root `pyproject.toml` `testpaths`
  so it runs with the repo suite instead of rotting.
  - `market.py` (93) — seeded synthetic `Broker` / `PriceFeed` / `Order` / `RebalancePlan` /
    `synthetic_portfolio`. No NOOA imports. Separate module *on purpose* — see gotchas.
  - `analyst.py` (119) — `PortfolioAnalyst`. Deterministic bodies (`max_position_pct`,
    `holdings`, `total_value`, `weights`, `projected_weights`) alongside the ellipsis-bodied
    `propose_rebalance`. `_broker_ready` precondition, `_within_position_cap` postcondition.
  - `demo.py` (77) — runnable entry point; resolves Ollama or the quickstart cascade.
  - `tests/` — 10 frozen tests (no key, no network) + `test_live.py` (integration marker).
  - **Verified 2026-08-04:** 10 frozen pass; full repo suite 6430 passed / 5 skipped
    (`pytest -q --ignore=tests/test_mcp`; the 4 MCP collection errors are the pre-existing
    uninstalled-extra ones and now *interrupt* collection, so ignore that dir); ruff clean.
  - **Mutation-checked, not just green.** Removing either condition fails 3 tests; perturbing
    the correlation window one day fails the live-frame test. Do this again after any edit —
    project 03's worst bug was invisible to five green tests.
  - **The live path reaches the postcondition on a real model** but has never produced a
    *passing* plan. See "Project 01 — where the live run got to" below.

## Next task

**Finish Project 01's live run, then write it up.** The code is done and frozen-tested; what is
missing is a live run that ends in a cap-compliant plan, and the HTML explainer that needs those
traces. Two sub-tasks, in order:

1. **Get one clean live run.** Two *plumbing* faults were found and fixed on 2026-08-04 — the
   4096-token context window and the model-switch stall. Both are written up under "Project 01 —
   where the live run got to"; read that before touching anything, because the previous version of
   this file blamed model reasoning and was wrong. What is left really is the model: it has to write
   a converging fixed-point loop. Options, cheapest first: reword the `propose_rebalance` docstring;
   try `llama3.1:8b` or `qwen3:8b`; or an API key with credits (the `OPENAI_API_KEY` in the env is
   **out of credits** — confirmed 2026-08-04). **Do not simply raise `max_retries`** — at a
   too-small window that makes things actively worse, and it is what the last two sessions wasted
   time on.
2. **Write `docs/nooa-project-01-explained.html`** in the style of `nooa-project-03-explained.html`
   (layered: plain-language boxes + exhaustive walkthrough), then **add a README table row** or
   nobody will find it. Run the HTML anchor checker afterwards (see scratch section).

Optional once live traces exist: record goldens for the analyst using project 03's
`golden_trajectory` fixture. That would make 01 the first consumer of 03 — a genuinely good
demonstration — but needs `nooa_bench` importable from `examples/portfolio/tests`, which it is
not today.

Parallel/backup tracks if 01 blocks:

- **Wire project 03 into CI** (plan phase 6). A few lines; would gate pushes on the 53 frozen tests.
- **Report bug 2 upstream** (see below) — the one finding useful to people other than us.
- **Verify `docs/` against a real run.** The quickstart's 7 steps and every CLI command were
  transcribed from source and never executed. Acceptance: quickstart runs clean from a fresh
  `uv sync --group dev`, trace viewer on `:5001`. Sandbox first.
- If the user asks for something else, that takes precedence.

## Project 01 — where the live run got to (2026-08-04)

**The mechanism works end to end against a real model. Two plumbing faults were misdiagnosed as
model arithmetic; both are now fixed. A third blocker — the model writing a converging loop —
is real and still open.**

> **WAS (superseded 2026-08-04):** this section used to open "The model's arithmetic is the
> blocker" and recommended raising `max_retries`. That was wrong on both counts. Ollama was serving
> a 4096-token window while the *opening* prompt was already ~2300 tokens, so each retry pushed the
> conversation further past the limit and Ollama dropped text from the **front** — deleting the cap
> instructions and tool definitions the model was being judged against. More retries made it worse.
> See "Ollama's default context window" in the gotchas.

Best run so far (`qwen2.5:7b`, `max_retries=3`): the model called `execute_python`, wrote pandas
against the real in-memory frame, built a `RebalancePlan` in code, and called `return_result` from
*inside* the cell. The postcondition then refused it with

> `Plan rejected: AAPL would be 25.1%, MSFT would be 25.1%, NVDA would be 25.1%, but
> max_position_pct() is 15%.`

That is feature J *observed* rather than asserted. It then failed to converge in 3 retries, which
is why `max_retries` is now 6. **No live run has yet ended in a passing plan.**

**Model selection is the trap, not model size.** Measured against Ollama:

| Model | Native tool calls | Outcome |
|---|---|---|
| `qwen2.5:1.5b` | yes | too weak — 4/4 runs never called `execute_python` |
| `qwen2.5-coder:7b` | **no** | unusable — cannot drive CodeAct at all |
| `qwen2.5:7b` | yes | reaches the live objects and the postcondition |

`qwen2.5-coder:7b` is the one that costs a session if you don't know. `/api/show` reports
`capabilities: completion,tools,insert`, but posting a tools array straight to `/api/chat` returns
`tool_calls: null` with the call as JSON in `content` — and it invents the tool name `run_python`
instead of the `execute_python` it was given. Its chat template does not emit Ollama's tool-call
format. **Diagnostic before blaming NOOA or LiteLLM:**

```bash
curl -s http://127.0.0.1:11434/api/chat -d '{"model":"<m>","stream":false,
  "messages":[{"role":"user","content":"Compute 2+2 in Python."}],
  "tools":[{"type":"function","function":{"name":"execute_python","description":"Run a code cell",
  "parameters":{"type":"object","properties":{"code":{"type":"string"}},"required":["code"]}}}]}'
```
If `message.tool_calls` is null and the call is sitting in `message.content`, the model is unusable
for CodeAct — no framework can recover from it.

Both 7B models are on disk (~4.7 GB each). `ollama rm qwen2.5-coder:7b` reclaims the dead one.
Start the server with `OLLAMA_HOST=0.0.0.0`; from WSL the gateway is `172.26.16.1` (re-check with
`ip route show default`, it changes).

**`test_live.py` fails rather than skips on `GenerationError`, deliberately.** See the corrected
bug below for why.

## Known-open issues in the harness

- **Bug 2 — `parallel_tool_calls` breaks CodeAct on Ollama. Worked around in tests only.**
  `litellm.UnsupportedParamsError: ollama_chat does not support parameters: ['parallel_tool_calls']`.
  `drop_params` appears 5× in `tests/`, **0× in `src/`** — deliberately, since it is global mutable
  state on `litellm` and belongs to the caller. Consequence: anyone using `nooa-bench` against
  Ollama with CodeAct still hits this. Not our bug (NOOA ↔ LiteLLM ↔ Ollama), but it contradicts
  the ideas doc's "local models are first-class... with no API key" — true for generation, false
  for CodeAct. **Not reported upstream.**
- **Skip-based flakiness handling has a ceiling — and it fired. CONFIRMED 2026-08-04, not
  hypothetical.** `packages/nooa-bench/tests/test_live_ollama.py` reports "3 passed, 1 skipped"
  against *both* `qwen2.5:1.5b` and `qwen2.5:7b`, and the skipped one is the CodeAct test, skipping
  on `GenerationError` **every single run**. A green suite that had verified nothing — the exact
  rubber-stamp this entry predicted. Always run it with `-rs` and read the skip reason; "3 passed"
  is not evidence that CodeAct works on Ollama. This is why `examples/portfolio/tests/test_live.py`
  fails rather than skips.
- **The live run has no HTTP timeout, so a stall is indistinguishable from slow work.** A run was
  found 1h36m in with 90 ms of total CPU and an idle ESTABLISHED socket; `demo.py` prints nothing
  between the opening table and the final plan, so there was no way to tell. Runs are currently
  bounded with a shell `timeout -s INT 2700`, which is a wrapper, not a fix — `CompletionClient`
  takes an `http_config` with real timeout settings. **That 96-minute stall is still unexplained**:
  the model-switch stall above accounts for minutes, not hours, and closing it out needs the Ollama
  server log, which nobody has read yet.
- **`qwen2.5:7b` gets the units wrong, unprompted.** From a recorded live trace it computes
  `shares_to_sell = (weight - cap) * self.total_value()` — a *dollar* amount — and passes it
  straight into `Order(shares=...)`, never dividing by `self.prices.last(symbol)`. Open judgement
  call: hint at it in the docstring, or leave it as an honest demonstration of what the
  postcondition exists to catch.
- **`max_retries=6`'s justifying comment (`analyst.py:108-111`) rests on a falsified premise.** It
  assumes more rounds help. At 4096 tokens they hurt. Whether 6 is right at 16384 is untested.
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
- **`git status` inside WSL lists the ENTIRE tree as modified.** Hundreds of ` M` lines over the
  `/mnt/c` 9p mount (filemode/CRLF differences between the two git configs). It looks like
  catastrophic corruption and invites a `git checkout .` that would destroy real work. Windows git
  showed exactly 2 real entries at the same moment. **Run pytest/ruff in WSL, run every `git`
  command from Windows.**
- **How live objects actually reach the REPL** (verified by execution, not by reading):
  `exec_globals["self"] = self.agent` at `src/nooa/runtime/actor.py:1387` — the *real* agent
  object, no copy, no serialization. Deterministic methods are **not** injected as bare names and
  are **not** tools; they are reachable only as `self.method(...)`. The LLM gets exactly two tools,
  `execute_python` and `return_result` (`codeact.py:789-791`). Caveat: under
  `execution_backend="sandbox"` (not the default) `self` becomes a `ParentAgentProxy` and every
  attribute hop is IPC.
- **Agent fields reach the prompt through two different blocks** (`src/nooa/agent.py:241-247`):
  `<self>` = `doc(type(self))`, **types only**, static — so a field needs a *class-level
  annotation* to appear at all; assigning it only in `__init__` renders nothing. `<state>` =
  `pformat(self, ...)`, **live values**, re-rendered every turn — a DataFrame arrives as its real
  `repr`, truncated to `DataFrame(repr_len=N, [:250]=..., [-250:]=...)` past `max_string`.
- **`Annotated[str, hidden]` is prompt redaction, not access control.** It drops the field from
  both blocks (`agent.py:558`, `:589`) — verified: a planted secret appears in zero messages — but
  `self.api_key` still resolves fine inside generated code. Note the asymmetry: module-level
  `hidden` *does* remove names from `exec_globals`; field-level `hidden` does not.
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
- **Ollama's default context window is 4096 and it silently truncates. This was the real project-01
  blocker, not model reasoning.** `/api/ps` reports `context_length` for a loaded model — check it.
  The opening CodeAct prompt for `PortfolioAnalyst` is already **~2277 tokens** (measured: 9,108
  chars over 6 messages), and each retry appends the rejected plan plus its pandas stdout. Past the
  limit Ollama drops from the *front*, which is exactly where `<execution_context>`, the tool
  definitions and the cap instructions live — so the retry loop deletes the rules it is being judged
  against. **Fix:** `CompletionClient(model=..., api_base=..., num_ctx=16384)`. `**config` is
  forwarded to litellm, and `num_ctx` is a real field on litellm's `OllamaChatConfig`
  (`llms/ollama/chat/transformation.py:95`); `litellm.drop_params = True` does *not* eat it.
  Verified by loading the **stock** `qwen2.5:7b` (digest `845dbda0…`) and reading back
  `"context_length":16384`. A hand-built `ollama create ... PARAMETER num_ctx` model also works but
  is not needed — do not ship one in a tutorial, readers will not have it.
  **Measure the prompt offline instead of guessing:** subclass the *fake* client
  (`examples/portfolio/tests/conftest.py::RecordingLLM`), run the agent with no scripted responses,
  and sum `len(str(m["content"]))` over the recorded messages. Seconds, no GPU, no network.
- **A stalled live run is usually Ollama refusing to switch models, not a dead request.** Ollama will
  not evict a resident model to load a different one until the incumbent's keep-alive expires. While
  it waits it accepts your TCP connection, reads the request, and says *nothing* — no error, no
  queue notice. The client sits in `do_epoll_wait` with an ESTABLISHED socket and, since nothing sets
  an HTTP timeout, waits forever. Diagnosis: `ss -tnp | grep 11434` (established, both queues 0) plus
  `curl /api/ps` showing a *different* model loaded. Fix in seconds with
  `curl .../api/generate -d '{"model":"<incumbent>","keep_alive":0}'` → `done_reason: unload`.
  Avoid it entirely by not switching models mid-session.
- **`pkill -f demo.py` kills itself.** The pattern matches `pkill`'s own command line, so it can die
  before killing the target and report success. This produced two concurrent runs fighting over one
  Ollama instance for five minutes, and readings that made no sense. **Kill by PID**
  (`ps -o pid,etime,cmd -C python3 --no-headers`, then `kill -9 <pid>`), and verify the process is
  gone rather than trusting the exit code.
- **Shell variables do not survive the trip into `wsl -- bash -lc '...'` from this harness.**
  `$(seq 1 60)` and `$n` arrive empty or mangled (`syntax error near unexpected token`,
  `[: -lt: unary operator expected`). Write poll loops with literal word lists —
  `for i in 1 2 3 4 5; do ...; done` — and no variable references inside.
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
# Project 01 — frozen (no key, no network)
uv run --frozen pytest examples/portfolio/tests             # 10 passed, 1 deselected
# Project 01 — live
OLLAMA_API_BASE=http://172.26.16.1:11434 OLLAMA_MODEL=ollama_chat/qwen2.5:7b \
  uv run --frozen python examples/portfolio/demo.py
# whole repo (MCP dir must be ignored — it now *interrupts* collection)
uv run --frozen pytest -q --ignore=tests/test_mcp           # 6430 passed, 5 skipped

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
- **Prompt-inspection probe** (`probe2.py`) — the tool that answered "how do live objects reach the
  REPL". Subclass `FakeLLMClient`, override `acall` to append `[dict(m) for m in messages]` to a
  module-level list, script one `execute_python` turn plus one `return_result`, run the agent, then
  dump every recorded message to a file. That transcript *is* the rendered system prompt —
  `<execution_context>`, `<self>`, `<state>`, and the `PythonOutput` fed back after each cell.
  Worth 20 lines any time you need to know what the model actually sees; far faster than reading
  `codeact.py`. The same idea is committed and reusable as
  `examples/portfolio/tests/conftest.py::RecordingLLM` (`.text()` flattens every message).
- **Prompt-size meter** (`ctx_size.py`) — ~30 lines. Insert `examples/portfolio` and its `tests` dir
  on `sys.path`, build `PortfolioAnalyst` with `RecordingLLM(scripted_responses=[])`, `await
  propose_rebalance(...)` inside a `try` (it ends in `GenerationError` — that is fine), then for each
  recorded message list print `len(msgs)` and `sum(len(str(m["content"])))`. Prints
  `prompt 0: 6 messages, 9108 chars, ~2277 tokens`. This is what caught the 4096-window bug in
  seconds after two sessions of blaming the model. Run it after any change to `analyst.py`'s fields
  or docstring.
- **Live tracer** (`trace_live.py`) — ~60 lines, the single most useful thing built this session.
  Subclass the *real* `CompletionClient`, override `acall` to append the message count, char count,
  the last inbound message and `resp.content` / `resp.tool_calls` to `/tmp/trace.txt` (flush every
  write), then run the agent. Turns "`GenerationError` after 8 iterations" into the actual Python the
  model wrote — which is how the infinite-loop and units bugs were found. `demo.py` prints nothing
  during the loop, so without this every failed live run is opaque.
- **Ollama tool-call check** (`tc.py`) — superseded by the `curl` one-liner in the Project 01
  section above. Use that.
- **Live run output** — `/tmp/live2.txt` inside WSL, from the `max_retries=6` run still in flight
  at session end. WSL `/tmp` survives `/clear` but not a reboot. Read it before re-running.
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
