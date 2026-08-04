# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the portfolio analyst against a real model.

    # any provider the repo's quickstart resolves (OPENAI_API_KEY, NVIDIA_API_KEY, ...)
    uv run --frozen python examples/portfolio/demo.py

    # or a local Ollama (from WSL, use the Windows gateway IP, not localhost)
    OLLAMA_API_BASE=http://172.26.16.1:11434 \\
      uv run --frozen python examples/portfolio/demo.py

Everything here is caller-side glue, deliberately outside ``analyst.py`` so it
never lands in the model's execution context.
"""

from __future__ import annotations

import asyncio
import os

from analyst import PortfolioAnalyst
from market import Broker, PriceFeed, synthetic_portfolio

THESIS = (
    "This book is far too concentrated in a single mega-cap. Bring every "
    "position under the cap while keeping broad market exposure."
)


def build_llm():
    """Resolve a client from the environment.

    ``litellm.drop_params`` is set only on the Ollama path. CodeAct sends
    ``parallel_tool_calls``, which ``ollama_chat`` rejects outright — see
    ``docs/HANDOFF.md`` "bug 2". It is global mutable state on ``litellm``, so
    it belongs to the caller (here) and not to ``analyst.py``.
    """
    api_base = os.environ.get("OLLAMA_API_BASE")
    if api_base:
        import litellm

        from nooa.unifiedllm import CompletionClient

        litellm.drop_params = True
        model = os.environ.get("OLLAMA_MODEL", "ollama_chat/qwen2.5:1.5b")
        return CompletionClient(model=model, api_base=api_base)

    from nooa.util.quickstart import llm

    return llm


def show(title: str, weights: dict[str, float], cap: float) -> None:
    """Print weights, flagging anything above the cap."""
    print(f"\n{title}")
    for sym, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        print(f"  {sym:<5} {w:>6.1%}  {'← OVER CAP' if w > cap + 1e-9 else ''}")


async def main() -> None:
    prices = PriceFeed()
    agent = PortfolioAnalyst(synthetic_portfolio(prices), Broker(), prices, llm=build_llm())
    cap = agent.max_position_pct()

    show(f"Before — cap is {cap:.0%} of ${agent.total_value():,.0f}", agent.weights(), cap)
    plan = await agent.propose_rebalance(THESIS)

    print(f"\nPlan: {plan.rationale}")
    for o in plan.orders:
        print(f"  {'SELL' if o.shares < 0 else 'BUY '} {abs(o.shares):>6} {o.symbol}")
    show("After (projected)", agent.projected_weights(plan.orders), cap)

    print(f"\nSubmitted {agent.broker.submit(plan.orders)} orders to the paper broker.")


if __name__ == "__main__":
    asyncio.run(main())
