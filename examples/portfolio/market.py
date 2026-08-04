# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Synthetic market objects for the portfolio-analyst demo.

Deliberately plain Python with no NOOA imports: these are the *live objects*
the agent holds by reference. Everything is seeded and in-memory, so the demo
never touches a network or a real account — which is also what removes the
sandboxing question. Model-generated code runs against a read-only frame and a
paper broker that records orders instead of sending them.

Kept in its own module because NOOA renders the *defining module's* namespace
into the system prompt; ``analyst.py`` stays small so the prompt does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

SYMBOLS = ("AAPL", "MSFT", "NVDA", "JPM", "XOM", "PFE", "KO", "CAT")
SECTORS = ("Tech", "Tech", "Tech", "Financials", "Energy", "Health", "Staples", "Industrials")


class Order(BaseModel):
    """One proposed trade. Negative ``shares`` sells."""

    symbol: str
    shares: int


class RebalancePlan(BaseModel):
    """What the model proposes. Validated by NOOA before it is ever returned."""

    orders: list[Order] = Field(default_factory=list)
    rationale: str = ""


class PriceFeed:
    """Deterministic pseudo-live prices: 180 daily closes per symbol.

    ``history`` is what makes the point. No tool anticipates a rolling
    correlation, a drawdown or a beta — the model just writes the pandas.
    """

    def __init__(self, seed: int = 7) -> None:
        rng = np.random.default_rng(seed)
        base = rng.uniform(30.0, 400.0, size=len(SYMBOLS))
        steps = rng.normal(0.0004, 0.018, size=(180, len(SYMBOLS)))
        path = base * np.exp(np.cumsum(steps, axis=0))
        self.history = pd.DataFrame(
            path,
            columns=list(SYMBOLS),
            index=pd.bdate_range("2026-01-02", periods=180),
        ).round(2)

    def last(self, symbol: str) -> float:
        """Most recent close for ``symbol``."""
        return float(self.history[symbol].iloc[-1])


class Broker:
    """Paper broker. Records orders; never sends one anywhere."""

    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.submitted: list[Order] = []

    def submit(self, orders: list[Order]) -> int:
        """Record ``orders`` and return how many were accepted."""
        if not self.connected:
            raise ConnectionError("broker is not connected")
        self.submitted.extend(orders)
        return len(orders)


def synthetic_portfolio(prices: PriceFeed, seed: int = 7) -> pd.DataFrame:
    """A holdings frame: symbol, sector, shares, cost basis.

    Deliberately concentrated in Tech so a thesis about diversification has
    something real to bite on.
    """
    rng = np.random.default_rng(seed)
    weight = np.array([3.0, 3.0, 4.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    shares = (rng.uniform(200, 600, size=len(SYMBOLS)) * weight).astype(int)
    return pd.DataFrame(
        {
            "symbol": list(SYMBOLS),
            "sector": list(SECTORS),
            "shares": shares,
            "cost_basis": [round(prices.last(s) * rng.uniform(0.7, 1.1), 2) for s in SYMBOLS],
        }
    ).set_index("symbol")
