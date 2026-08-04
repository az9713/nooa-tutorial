# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Project 01 — a portfolio analyst that reasons over live objects.

**Keep this module's namespace small.** NOOA renders the defining module's
globals into the ``<execution_context>`` block of the system prompt, so every
import and top-level name here reaches the model. The domain objects live in
``market.py`` for that reason; the two condition functions are underscored so
``agentdoc`` omits them.

The point of the demo is the boundary. ``total_value``, ``weights`` and
``projected_weights`` have real bodies — they are guarantees, and the model
calls them like any other Python. ``propose_rebalance`` has an ellipsis body —
it is a guess, and the position cap is enforced *around* it rather than
trusted inside it.
"""

from __future__ import annotations

from typing import Annotated, Any

from market import Broker, Order, PriceFeed, RebalancePlan
from pandas import DataFrame

from nooa import Agent, hidden, strategy
from nooa.config import CodeActConfig
from nooa.strategies import CodeActStrategy
from nooa.strategy_validation import InvariantError


def _broker_ready(agent: Any, call: Any) -> None:
    """Precondition: fail fast, before a single token is spent."""
    if not agent.broker.connected:
        raise InvariantError("broker is not connected — refusing to plan a rebalance")


def _within_position_cap(agent: Any, result: Any, call: Any) -> None:
    """Postcondition: the model is told *why* it was refused, and retries.

    Raising ``InvariantError`` (rather than any other exception) is what routes
    this back through CodeAct's validation-retry path instead of killing the
    run — ``src/nooa/strategies/codeact.py:1852``.
    """
    unknown = sorted({o.symbol for o in result.orders} - set(agent.weights()))
    if unknown:
        raise InvariantError(
            f"Plan rejected: {', '.join(unknown)} is not in the portfolio. "
            f"Only trade symbols present in self.portfolio.index."
        )
    cap = agent.max_position_pct()
    after = agent.projected_weights(result.orders)
    over = {s: w for s, w in after.items() if w > cap + 1e-9}
    if over:
        detail = ", ".join(f"{s} would be {w:.1%}" for s, w in sorted(over.items()))
        raise InvariantError(
            f"Plan rejected: {detail}, but max_position_pct() is {cap:.0%}. "
            f"Sell more of those names and propose again. "
            f"Call self.projected_weights(orders) to check before returning."
        )


class PortfolioAnalyst(Agent):
    """You analyse a live portfolio and propose rebalances."""

    portfolio: DataFrame
    broker: Broker
    prices: PriceFeed
    api_key: Annotated[str, hidden] = ""  # never rendered into a prompt

    def __init__(self, portfolio: DataFrame, broker: Broker, prices: PriceFeed, **kw: Any) -> None:
        super().__init__(**kw)
        self.portfolio = portfolio
        self.broker = broker
        self.prices = prices

    def max_position_pct(self) -> float:
        """The hard cap on any single position, as a fraction of total value."""
        return 0.15

    def holdings(self) -> dict[str, int]:
        """Share count per symbol."""
        return {str(s): int(self.portfolio.at[s, "shares"]) for s in self.portfolio.index}

    def total_value(self) -> float:
        """Current market value of all holdings."""
        return float(sum(n * self.prices.last(s) for s, n in self.holdings().items()))

    def weights(self) -> dict[str, float]:
        """Current portfolio weight per symbol."""
        total = self.total_value()
        return {s: n * self.prices.last(s) / total for s, n in self.holdings().items()}

    def projected_weights(self, orders: list[Order]) -> dict[str, float]:
        """Weights the portfolio *would* have after ``orders`` fill."""
        delta: dict[str, int] = {}
        for o in orders:
            delta[o.symbol] = delta.get(o.symbol, 0) + o.shares
        held = {
            s: max(n + delta.get(s, 0), 0) * self.prices.last(s) for s, n in self.holdings().items()
        }
        total = sum(held.values())
        return {s: v / total for s, v in held.items()} if total else dict.fromkeys(held, 0.0)

    @strategy(
        CodeActStrategy(
            config=CodeActConfig(
                max_iterations=8,
                preconditions=[_broker_ready],
                postconditions=[_within_position_cap],
            )
        )
    )
    async def propose_rebalance(self, thesis: str) -> RebalancePlan:
        """Propose a rebalance consistent with {thesis}.

        Analyse ``self.portfolio`` and ``self.prices.history`` directly with
        pandas. Every position must end at or below ``self.max_position_pct()``.
        """
        ...
