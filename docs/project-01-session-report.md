# Project 01 live run — session report (2026-08-04)

**Goal from `HANDOFF.md`:** get one clean live run of the portfolio analyst that ends in a
cap-compliant plan, then write `docs/nooa-project-01-explained.html`.

**Outcome: the goal was not reached.** No run has produced a plan that passes the position-cap
postcondition. What the session produced instead is four confirmed faults — three environmental, one
self-inflicted — a corrected diagnosis in `HANDOFF.md`, and two measurement tools that turn an opaque
40-minute failure into a readable trace. The HTML explainer is still blocked: it needs traces from a
passing run that does not exist.

Commits: `6929122` (fixes + handoff correction), `884df4f` (traced-run outcome). Both pushed to
`tutorial`. Working tree clean.

---

## 1. What was found on arrival

`HANDOFF.md` said a run with `max_retries=6` was in flight, writing to WSL `/tmp/live2.txt`.

It had been "running" for 1 hour 36 minutes. It was dead, not slow:

| Evidence | Reading | Meaning |
|---|---|---|
| `/proc/<pid>/stat` utime+stime | 90 ms total | Not computing anything |
| `ss -tnp` | ESTABLISHED socket to Ollama, both queues empty | Request sent, nothing returned |
| `/api/ps` | no model loaded | Ollama was not working on it either |
| the log | opening table, then nothing for 96 min | No way to tell from outside |

In plain terms: the program asked the model a question, the model never answered, and nothing was set
up to give up. `demo.py` prints nothing between the opening table and the final plan, so a hang and a
slow run look **identical**. That is what consumed the previous session.

---

## 2. Fault 1 — the context window was too small (measured, not guessed)

`HANDOFF.md` diagnosed the blocker as "model reasoning, not plumbing" and recommended more retries or
a bigger model. Ollama reported something suspicious when the model loaded:

```
"context_length": 4096
```

**How it was measured.** Rather than reason about it, the repo's own `RecordingLLM`
(`examples/portfolio/tests/conftest.py`) was reused in a throwaway script. It subclasses the *fake*
client and keeps every message list it is handed, so the real rendered prompt can be measured
offline — no network, no model, no waiting:

```
prompt 0:  6 messages,  9,108 chars, ~2,277 tokens
prompt 1:  9 messages,  9,694 chars, ~2,423 tokens
prompt 2: 12 messages, 10,281 chars, ~2,570 tokens
```

The **opening** prompt already fills ~2,277 of the 4,096-token budget, with a stub model that
generates nothing. A real run adds the model's Python cell plus that cell's printed output (a pandas
DataFrame is hundreds of tokens) every iteration, for up to 8 iterations × 6 retries.

Why this matters more than it looks: when a conversation crosses the window, Ollama drops text from
the **front** — where the system prompt lives: the position cap, the instructions, the tool
definitions. The retry loop was quietly deleting the rules the model was being judged against.
**More retries made it worse.** The recommendation to raise `max_retries` pushed the wrong way, and
the comment at `analyst.py:108-111` justifying `max_retries=6` rests on a premise this contradicts.

### The fix, and a wrong turn on the way

The first fix was a hand-built model with a bigger window (`ollama create qwen2.5:7b-16k`, Modelfile
`PARAMETER num_ctx 16384`). It worked but is wrong for a tutorial — readers would not have it.

The portable fix exists. `CompletionClient` documents `**config` as "additional configuration passed
to litellm," and `num_ctx` is a real field on litellm's `OllamaChatConfig`
(`llms/ollama/chat/transformation.py:95`):

```python
CompletionClient(model=model, api_base=api_base, num_ctx=16384)
```

**Verified by observation, not by reading docs.** Ollama reported the *stock* model — original digest
`845dbda0…`, not the hand-built one — serving `"context_length": 16384`. The concern that
`litellm.drop_params = True` might swallow the parameter did not materialise.

`qwen2.5:7b-16k` is now dead weight: `ollama rm qwen2.5:7b-16k`.

---

## 3. Fault 2 — the "hang" is Ollama refusing to switch models

A later run stalled the same way: ESTABLISHED socket, process parked in `do_epoll_wait`, no model
loading, no response.

Cause: Ollama already had a *different* model resident in VRAM. It will not evict one model to load
another until the incumbent's keep-alive expires. While waiting it accepts the connection, reads the
request, and says **nothing** — no error, no queue notice.

Confirmed by forcing the incumbent out:

```bash
curl .../api/generate -d '{"model":"qwen2.5:7b-16k","keep_alive":0}'
# → {"done_reason":"unload"}
```

The blocked request completed immediately and the stock model loaded. So this is a **self-inflicted,
transient** condition caused by switching models — not a broken request.

This revises an earlier claim made during this session that "the response never comes." It does come,
after the incumbent times out. It does **not** explain the original 96-minute hang — a 5-minute idle
timer cannot produce 96 minutes — which remains open.

---

## 4. Fault 3 — tooling errors that produced false readings

**`pkill -f demo.py` kills itself.** The pattern matches `pkill`'s own command line, so it can die
before killing the target and still look successful. A run was twice reported as "killed" while still
alive. Consequence: for about five minutes **two runs were live at once**, competing for one Ollama
instance, which is why the stock model never loaded and one set of readings made no sense. Kill by
PID and verify the process is gone.

**Shell variables do not survive into `wsl -- bash -lc '...'` from this harness.** `$(seq 1 60)` and
`$n` arrive empty or mangled (`syntax error near unexpected token`, `[: -lt: unary operator
expected`). Use literal word lists: `for i in 1 2 3 4 5; do ...; done`.

**A false confirmation.** The `16384` readings were cited as proof that `num_ctx` forwarded, when
every one of them was the hand-built `-16k` model. They proved nothing about the stock path. Real
evidence arrived two steps later, when the digest identified the stock model.

---

## 5. Fault 4 — a docstring edit made the model worse

With the bigger window, the run failed **differently**:

```
GenerationError: Generation failed after 8 iterations (max_iterations=8).
```

Previously the model produced a plan the cap postcondition refused (weights at 25.1%). Now it
produced **no plan at all**. The failure moved rather than improved.

Because `demo.py` is silent during the loop, a tracing client was built — a subclass of the real
`CompletionClient` logging every exchange to a file. Turn 1 showed the cause:

```python
while projected_cap := [symbol for symbol in current_weights.keys()
                        if current_weights[symbol] > self.max_position_pct()]:
    for symbol in projected_cap:
        symbol_orders.append(Order(symbol=symbol, shares=-int(shares_to_sell)))
```

`current_weights` is never recomputed, so the condition can never go false — an **infinite loop**
appending orders forever.

This was self-inflicted. Step 3 of the `propose_rebalance` docstring had been rewritten earlier in
the session to say *"Loop instead… repeat until none is."* The model followed it literally and looped
over a variable it never updates. The previous wording described the *effect* and at least produced a
finite, if over-cap, plan.

**Process mistake:** the docstring and the context window were changed before the same run, so the
changed outcome could not be attributed cleanly. The trace resolved it after the fact; the two should
have been tested separately.

---

## 6. The corrected docstring, tested alone

Step 3 was reworded to mandate a **bounded** loop, require recomputation inside it, and name the trap:

> Refine over a **fixed** number of passes — `for _ in range(5):` is plenty. Every pass must call
> `self.projected_weights(orders)` again for fresh weights… Never loop on `self.weights()` or on a
> snapshot taken before the loop: that value does not change as you append orders, so a `while` over
> it never terminates.

Re-run with that change alone (`num_ctx` already verified and unchanged). **Result: still no plan**,
40-minute wall reached at turn 7. Two things it settled:

- **The window fix works and the measurement holds.** Turn 1 ~2,323 tokens → turn 7 ~4,837, roughly
  400/turn. At the old 4,096 default this run would have begun truncating around turn 5, mid retry
  loop. It never approached 16,384, so context is no longer the constraint.
- **The reword achieved its structural goal.** The model now writes
  `for _ in range(5): projected_weights = self.projected_weights(initial_orders); … break`. The
  infinite `while` is gone.

What blocks it now is plain code quality, and it is a **stuck** loop rather than a diverging one:
from turn 4 the model re-emits a near-identical cell that cannot run.

| Fault in the generated cell | Effect |
|---|---|
| `max_position_pct` as a bare unbound name inside the loop | `NameError` every pass (it calls `self.max_position_pct()` correctly *above* the loop) |
| `from pandas import pformat, isin, notna, …` | several do not exist → `ImportError` |
| stray `}}` mid-function in one cell | hard `SyntaxError` |
| `(1 - cap) * self.prices.history['close'].sum() / projected_weights[symbol]` | `history` has no `'close'` column — it is one column per symbol |
| `shares_to_sell = (weight - cap) * self.total_value()` passed to `Order(shares=…)` | dollars used as a share count; never divides by price |

The last one predates every docstring edit and is a genuine finding about the model.

---

## 7. Files changed (committed and pushed)

| File | Change |
|---|---|
| `examples/portfolio/demo.py` | `num_ctx=16384` on the Ollama client + docstring explaining it is a correctness fix, not tuning |
| `examples/portfolio/analyst.py` | Step 3 of `propose_rebalance` reworded to a bounded, recomputing loop |
| `docs/HANDOFF.md` | Corrected diagnosis, both new gotchas, the `pkill` trap, rebuild notes for the scratch tools, traced-run outcome |

Checks before committing: 10/10 frozen tests, `ruff check` and `ruff format --check` clean.

**Scratch tooling** (rebuild notes are in `HANDOFF.md`; the files themselves were session-temporary):

- `ctx_size.py` — measures the rendered prompt offline via `RecordingLLM`. Caught the 4096-window bug
  in seconds after two sessions of blaming the model.
- `trace_live.py` — subclasses the real `CompletionClient` and dumps every exchange. This turned
  "`GenerationError` after 8 iterations" into the actual Python the model wrote, and is how both the
  infinite-loop and the units bug were found.

---

## 8. Outstanding issues

**Blocking the stated goal:**

1. **No cap-compliant plan.** The actual deliverable, not done.
2. **`docs/nooa-project-01-explained.html` not started**, and it needs a README table row when it
   lands.

**Unresolved:**

3. **The original 96-minute hang is unexplained.** Model-switch blocking accounts for minutes, not
   hours. Closing it needs the Ollama server log, which has not been read.
4. **No client-side HTTP timeout.** Runs are bounded by a shell `timeout -s INT 2700` — a wrapper,
   not a fix. `CompletionClient` accepts an `http_config` with real timeout settings.
5. **`max_retries=6` should be revisited.** Its justifying comment assumes retries help; at 4,096
   tokens they hurt. Whether 6 is right at 16,384 is untested.
6. **Where `num_ctx` belongs.** It sits in `demo.py` beside `litellm.drop_params`, which is
   defensible — both are caller-side transport concerns. But a reader copying `analyst.py` alone
   silently inherits the 4,096 default and this entire failure mode. Worth deciding before the
   explainer documents one or the other.
7. **The model's units bug is unaddressed.** Hint at it in the docstring, or leave it as an honest
   demonstration of what the postcondition exists to catch? A judgement call about the tutorial's
   purpose.

**Housekeeping:**

8. `ollama rm qwen2.5:7b-16k` — redundant now.

---

## 9. Recommendation

**Stop rewording the docstring.** Three revisions have moved the *shape* of the failure without
fixing it, and what remains are basic Python/pandas errors rather than misunderstandings of the task.
The next lever is a different model — `llama3.1:8b` or `qwen3:8b` (neither on disk; `ollama pull`
first, and run the tool-call diagnostic in `HANDOFF.md` before trusting either) — or a funded API key.
Not more retries, and not a longer window; the window is no longer the constraint.

One good outcome regardless of convergence: **the postcondition did its job.** It caught an over-cap
plan from a real model, and the tracing shows exactly why the model got it wrong. That is the demo's
actual thesis, and it holds whether or not the model ever satisfies the cap.
