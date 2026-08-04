# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Frozen tests for the portfolio analyst.

No API key, no network: the model is a ``FakeLLMClient`` replaying a fixed
script. The *code in the script still executes for real* against the live
DataFrame the agent holds, which is the whole point — these tests exercise the
live-object path, not a mock of it.

Run:

    uv run --frozen pytest examples/portfolio/tests
"""

from __future__ import annotations

import json

import pytest
from market import Order

from nooa.errors import GenerationError
from nooa.unifiedllm import LLMResponse, ToolCall


def response(content: str, tool_calls: list[ToolCall] | None = None) -> LLMResponse:
    """A scripted assistant reply."""
    return LLMResponse(
        raw_response=None,
        content=content,
        tool_calls=tool_calls or [],
        finish_reason="tool_calls" if tool_calls else "stop",
        assistant_message={"role": "assistant", "content": content},
        usage={"prompt_tokens": 50, "completion_tokens": 10},
    )


def exec_call(code: str, call_id: str) -> ToolCall:
    """An ``execute_python`` tool call — a cell the model "wrote"."""
    return ToolCall(id=call_id, name="execute_python", arguments=json.dumps({"code": code}))


# ── The scripted "model" turns ──────────────────────────────────────────
# Each of these is a Python cell the model would have written. They run
# unmodified inside the CodeAct REPL, against `self` — the real agent.

NAIVE_CELL = """
plan = RebalancePlan(orders=[Order(symbol="NVDA", shares=-100)],
                     rationale="Trim NVDA a little.")
return_result(plan)
"""

EQUAL_WEIGHT_CELL = """
w = self.weights()
value = self.total_value()
target = 1.0 / len(w)
orders = []
for sym, weight in w.items():
    delta = int((target - weight) * value / self.prices.last(sym))
    if delta:
        orders.append(Order(symbol=sym, shares=delta))
plan = RebalancePlan(orders=orders, rationale="Equal-weight to clear the cap.")
return_result(plan)
"""

# Nobody defined a `compute_correlation` tool. The model just writes pandas.
CORRELATION_CELL = """
returns = self.prices.history.pct_change().dropna()
corr = returns["NVDA"].tail(30).corr(returns["AAPL"].tail(30))
print("CORR30", round(float(corr), 6))
"""

UNKNOWN_SYMBOL_CELL = """
plan = RebalancePlan(orders=[Order(symbol="TSLA", shares=10)], rationale="New name.")
return_result(plan)
"""


# ── The deterministic half: real bodies, therefore guarantees ───────────


def test_cap_is_deterministic(analyst):
    """``max_position_pct`` has a real body — no model can move it."""
    assert analyst().max_position_pct() == 0.15


def test_starting_portfolio_breaches_the_cap(analyst):
    """The demo only means something if there is something to fix."""
    w = analyst().weights()
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["NVDA"] > 0.15


def test_projected_weights_models_the_trade(analyst):
    """Selling shares lowers that position's projected weight."""
    agent = analyst()
    before = agent.weights()["NVDA"]
    after = agent.projected_weights([Order(symbol="NVDA", shares=-1500)])["NVDA"]
    assert after < before
    # And it is a projection only — the live frame is untouched.
    assert agent.weights()["NVDA"] == pytest.approx(before)


# ── The precondition: fail fast, before a token is spent ────────────────


async def test_disconnected_broker_never_reaches_the_model(analyst):
    """A precondition runs before generation, so the LLM is never called."""
    agent = analyst(connected=False)
    with pytest.raises(Exception, match="broker is not connected"):
        await agent.propose_rebalance("de-risk")
    assert agent._llm.call_count == 0


# ── Feature D: the model computes against the object, not a schema ──────


async def test_model_runs_pandas_against_the_live_frame(analyst, prices):
    """A 30-day rolling correlation that no tool schema anticipated.

    The cell reaches ``self.prices.history`` — the same DataFrame object the
    agent holds (``src/nooa/runtime/actor.py:1387`` binds the real ``self``
    into the exec globals). Asserting the printed number against the same
    computation done here proves the cell ran on the real data.
    """
    agent = analyst(
        [
            response("Check the correlation first.", [exec_call(CORRELATION_CELL, "c1")]),
            response("Now rebalance.", [exec_call(EQUAL_WEIGHT_CELL, "c2")]),
        ]
    )
    await agent.propose_rebalance("cut the tech correlation")

    returns = prices.history.pct_change().dropna()
    expected = float(returns["NVDA"].tail(30).corr(returns["AAPL"].tail(30)))
    assert f"CORR30 {round(expected, 6)}" in agent._llm.text()


async def test_the_live_frame_is_rendered_into_the_prompt(analyst):
    """The ``<state>`` block carries real values, refreshed every turn."""
    agent = analyst([response("Rebalance.", [exec_call(EQUAL_WEIGHT_CELL, "c1")])])
    await agent.propose_rebalance("equal weight")
    seen = agent._llm.text()
    assert "<state" in seen
    assert "NVDA" in seen and "Industrials" in seen  # the actual frame contents


async def test_hidden_keeps_the_api_key_out_of_every_prompt(analyst):
    """``Annotated[str, hidden]`` is prompt redaction — and it holds."""
    agent = analyst([response("Rebalance.", [exec_call(EQUAL_WEIGHT_CELL, "c1")])])
    agent.api_key = "sk-must-never-be-rendered"
    await agent.propose_rebalance("equal weight")
    assert "sk-must-never-be-rendered" not in agent._llm.text()
    # Redaction, not access control: the agent itself still has it.
    assert agent.api_key == "sk-must-never-be-rendered"


# ── Feature J: rejected, told why, retried ─────────────────────────────


async def test_over_cap_plan_is_refused_and_the_model_retries(analyst):
    """The run does not die. The model is handed the reason and tries again."""
    agent = analyst(
        [
            response("Small trim should do.", [exec_call(NAIVE_CELL, "c1")]),
            response("Understood — equal-weighting.", [exec_call(EQUAL_WEIGHT_CELL, "c2")]),
        ]
    )
    plan = await agent.propose_rebalance("no position over the cap")

    # The refusal reached the model, naming the offending position and the cap.
    seen = agent._llm.text()
    assert "Plan rejected" in seen and "NVDA would be" in seen and "15%" in seen
    # And the plan that came back actually satisfies the constraint.
    after = agent.projected_weights(plan.orders)
    assert max(after.values()) <= agent.max_position_pct() + 1e-9
    assert agent._llm.call_count == 2


async def test_orders_outside_the_portfolio_are_refused(analyst):
    """Model-generated symbols are validated at the boundary, not trusted."""
    agent = analyst([response("Add Tesla.", [exec_call(UNKNOWN_SYMBOL_CELL, "c1")])] * 4)
    with pytest.raises(GenerationError):
        await agent.propose_rebalance("diversify")
    assert "TSLA is not in the portfolio" in agent._llm.text()


# ── The broker is only ever handed a plan that passed ──────────────────


async def test_broker_receives_only_a_validated_plan(analyst):
    """Submission is deterministic Python, downstream of the guarantee."""
    agent = analyst(
        [
            response("Small trim should do.", [exec_call(NAIVE_CELL, "c1")]),
            response("Equal-weighting.", [exec_call(EQUAL_WEIGHT_CELL, "c2")]),
        ]
    )
    plan = await agent.propose_rebalance("no position over the cap")
    assert agent.broker.submit(plan.orders) == len(plan.orders)
    # Whatever the broker was handed is, by construction, cap-compliant:
    # the naive first attempt never got past the postcondition.
    submitted = agent.projected_weights(agent.broker.submitted)
    assert max(submitted.values()) <= agent.max_position_pct() + 1e-9
    assert Order(symbol="NVDA", shares=-100) not in agent.broker.submitted
