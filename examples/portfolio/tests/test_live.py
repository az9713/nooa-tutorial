# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Live-model test for the portfolio analyst. Deselected by default.

    OLLAMA_API_BASE=http://172.26.16.1:11434 \\
      uv run --frozen pytest examples/portfolio/tests/test_live.py -m integration

**This needs a model that can actually do CodeAct.** ``qwen2.5:1.5b`` cannot:
in 4 consecutive runs on 2026-08-04 it never once called ``execute_python``.
Every time it wrote correct-looking pandas against ``self.portfolio`` and
``self.weights()`` — and then passed the whole cell to ``return_result`` as a
**string**, so CodeAct rejected it as ``Expected: RebalancePlan, Got: str``
three times and raised ``GenerationError``. It also invented
``max_position_pct = 0.5`` instead of calling ``self.max_position_pct()``,
which is precisely why the cap is enforced by a postcondition rather than
trusted to the model.

This test therefore **fails** rather than skips when generation fails. A skip
would be a rubber stamp: a model that always fails would leave the suite
looking green forever (``docs/HANDOFF.md``, "skip-based flakiness handling has
a ceiling"). It skips only when there is no endpoint to talk to at all.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest
from analyst import PortfolioAnalyst
from market import Broker, PriceFeed, synthetic_portfolio

pytestmark = pytest.mark.integration

API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "ollama_chat/qwen2.5:1.5b")


@pytest.fixture
def live_llm():
    """A real client, or a skip if nothing is listening."""
    try:
        urllib.request.urlopen(f"{API_BASE}/api/tags", timeout=3).read()
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"no Ollama at {API_BASE}: {exc}")

    import litellm

    from nooa.unifiedllm import CompletionClient

    # See docs/HANDOFF.md "bug 2": ollama_chat rejects parallel_tool_calls,
    # which CodeAct always sends. Caller-side global, as upstream intends.
    litellm.drop_params = True
    return CompletionClient(model=MODEL, api_base=API_BASE)


async def test_a_real_model_produces_a_cap_compliant_plan(live_llm):
    """End to end: real model, live DataFrame, enforced cap."""
    prices = PriceFeed()
    agent = PortfolioAnalyst(synthetic_portfolio(prices), Broker(), prices, llm=live_llm)
    assert agent.weights()["NVDA"] > agent.max_position_pct()  # there is work to do

    plan = await agent.propose_rebalance(
        "Far too concentrated in one mega-cap. Bring every position under the cap."
    )

    # The postcondition already guaranteed this — re-asserting it here is what
    # makes the test meaningful if the postcondition is ever weakened.
    after = agent.projected_weights(plan.orders)
    assert max(after.values()) <= agent.max_position_pct() + 1e-9
    assert set(after) == set(agent.weights())
