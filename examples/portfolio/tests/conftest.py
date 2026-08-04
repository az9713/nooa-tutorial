# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the portfolio-analyst demo.

The repo runs pytest with ``--import-mode=importlib``, which does not put the
test directory on ``sys.path``; the inserts below restore plain imports of
``analyst`` / ``market`` one level up. Same pattern as
``packages/nooa-bench/tests/conftest.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analyst import PortfolioAnalyst  # noqa: E402
from market import Broker, PriceFeed, synthetic_portfolio  # noqa: E402

from nooa.unifiedllm import FakeLLMClient, LLMResponse  # noqa: E402


class RecordingLLM(FakeLLMClient):
    """A ``FakeLLMClient`` that keeps every message list it was handed.

    The demo's central claims are about what the model *sees* — the live
    DataFrame in the ``<state>`` block, the absent API key, the rejection
    reason on retry. Asserting on those needs the transcript, and
    ``FakeLLMClient`` keeps only the last one.
    """

    def __init__(self, scripted_responses: list[LLMResponse] | None = None) -> None:
        super().__init__(scripted_responses=scripted_responses)
        self.transcript: list[list[dict[str, Any]]] = []

    async def acall(self, messages, tools=None, output_model=None, **kw):  # type: ignore[no-untyped-def]
        self.transcript.append([dict(m) for m in messages])
        return await super().acall(messages, tools, output_model, **kw)

    def text(self) -> str:
        """Every message body, flattened — for "does X reach the model?" checks."""
        return "\n".join(str(m.get("content")) for msgs in self.transcript for m in msgs)


@pytest.fixture
def prices() -> PriceFeed:
    """A seeded 180-day price history."""
    return PriceFeed()


@pytest.fixture
def analyst(prices):
    """Build an analyst over the synthetic portfolio with a scripted model."""

    def _build(script: list[LLMResponse] | None = None, *, connected: bool = True):
        llm = RecordingLLM(scripted_responses=script or [])
        return PortfolioAnalyst(
            synthetic_portfolio(prices),
            Broker(connected=connected),
            prices,
            llm=llm,
        )

    return _build
