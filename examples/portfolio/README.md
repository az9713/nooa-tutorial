# Project 01 — portfolio analyst over live objects

A single agent that holds a real `DataFrame`, a broker and a price feed as typed
fields, and proposes rebalances by writing pandas **against those objects** —
not against a tool schema somebody had to anticipate in advance.

```
market.py     Broker, PriceFeed, Order, RebalancePlan, synthetic_portfolio  (no NOOA)
analyst.py    PortfolioAnalyst — the agent, plus its pre/postconditions
demo.py       runnable entry point against a real model
tests/        10 frozen tests (no key, no network) + 1 live test (opt-in)
```

## Run it

```bash
# frozen — deterministic, no API key, no network
uv run --frozen pytest examples/portfolio/tests          # 10 passed, 1 deselected

# live, against a local Ollama (see the caveat below)
OLLAMA_API_BASE=http://172.26.16.1:11434 \
  uv run --frozen python examples/portfolio/demo.py
```

This repo cannot run natively on Windows (`src/nooa/storage/sqlite.py` imports
`fcntl`) — use WSL, with the venv outside `/mnt/c`.

## What it demonstrates

**Live objects (the headline).** `exec_globals["self"]` is bound to the real
agent instance — `src/nooa/runtime/actor.py:1387`. No copy, no serialization,
no JSON round-trip. So a cell can do

```python
returns = self.prices.history.pct_change().dropna()
corr = returns["NVDA"].tail(30).corr(returns["AAPL"].tail(30))
```

against 180 days × 8 symbols that already exist in memory. Nobody wrote a
`compute_correlation` tool, and nobody has to write the next one either. The
set of analyses the model can perform is no longer bounded by the set you
predicted. `test_model_runs_pandas_against_the_live_frame` pins this by
comparing the number the cell printed against the same computation done in the
test — it can only match if the cell ran on the real data.

**The deterministic/generated boundary is syntactic.** `max_position_pct()`,
`total_value()`, `weights()` and `projected_weights()` have real bodies, so
they are guarantees. `propose_rebalance()` has an `...` body, so it is a guess.
"Which parts of my trading logic are allowed to be wrong" becomes a property
you can read off the class.

**Preconditions fail fast; postconditions teach.** A disconnected broker is
caught *before* generation — `test_disconnected_broker_never_reaches_the_model`
asserts `call_count == 0`, so not a single token is spent. An over-cap plan is
caught *after*, and because the check raises `InvariantError` specifically, it
is routed back to the model as correctable feedback rather than killing the run
(`src/nooa/strategies/codeact.py:1852`). The model is told *which* position
breached and by how much, and re-proposes.

**`hidden` is prompt redaction, not access control.** `api_key: Annotated[str,
hidden]` is dropped from both the `<self>` block (types) and the `<state>`
block (live values) — `src/nooa/agent.py:558`, `:589`. `test_hidden_keeps_the_
api_key_out_of_every_prompt` asserts the secret appears in no message, *and*
that the agent can still read it. NOOA's visibility system does not gate
anything at runtime; runtime gating is what the pre/postconditions are for.

## Two things to know before extending it

**Keep `analyst.py`'s namespace small.** NOOA renders the defining module's
globals into the `<execution_context>` block, so every import and top-level
name in that file reaches the model. That is why the domain objects live in
`market.py` and the condition functions are underscore-prefixed.

**A 1.5B model is not enough.** In 4 consecutive runs on 2026-08-04,
`qwen2.5:1.5b` never called `execute_python` once. It wrote correct-looking
pandas against `self.portfolio` and `self.weights()` every time, then handed
the whole cell to `return_result` as a *string* — rejected three times as
`Expected: RebalancePlan, Got: str`, then `GenerationError`. It also made up
`max_position_pct = 0.5` rather than calling `self.max_position_pct()`, which
is a tidy argument for enforcing the cap outside the model. `tests/test_live.py`
therefore **fails** rather than skips on generation failure; it skips only when
there is no endpoint at all.

## Safety

Everything is synthetic, seeded and in-memory. The broker records orders and
sends them nowhere. NOOA's AST checks are not a containment boundary — if you
point this at real data or a real account, put OS-level isolation around it
first.
