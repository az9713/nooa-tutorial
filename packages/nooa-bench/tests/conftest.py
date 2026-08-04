# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pytest wiring for golden-trajectory regression tests.

Provides the ``golden_trajectory`` fixture and the ``--golden-update`` flag.
Golden files live in ``tests/golden/<test name>.json`` and are committed — the
diff in a pull request is the review artifact.

Kept in a conftest rather than registered as a ``pytest11`` entry point so it
needs no edit to a tracked ``pyproject.toml``. The repo runs pytest with
``--import-mode=importlib``, which does not put this directory on
``sys.path``; the insert below restores plain sibling imports so tests can
share ``golden_agents``.

The fixture agents deliberately live in that separate module rather than here:
NOOA renders the defining module's namespace into the system prompt, so a new
helper in this file would change every recorded prompt.

``GOLDEN_UPDATE=1`` does the same job as ``--golden-update`` and works however
pytest was invoked.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from golden_agents import (  # noqa: E402
    CodeActAgent,
    FanOutAgent,
    codeact_script,
    fanout_script,
)
from nooa_bench.trajectory import capture, check, normalize  # noqa: E402

from nooa.unifiedllm import FakeLLMClient, LLMResponse  # noqa: E402

GOLDEN_DIR = Path(__file__).parent / "golden"


# ---------------------------------------------------------------------------
# Fixture agents
# ---------------------------------------------------------------------------


@pytest.fixture
def codeact_agent() -> Callable[..., CodeActAgent]:
    """Factory: a CodeAct agent with a fresh scripted client.

    Pass ``llm=`` to supply your own client — a recorder or a replayer.
    """

    def make(turns: int = 3, llm: Any = None) -> CodeActAgent:
        return CodeActAgent(llm=llm or FakeLLMClient(scripted_responses=codeact_script(turns)))

    return make


@pytest.fixture
def fanout_agent() -> Callable[..., FanOutAgent]:
    """Factory: a fan-out agent with enough scripted replies for ``n`` items."""

    def make(n: int = 5, llm: Any = None) -> FanOutAgent:
        return FanOutAgent(llm=llm or FakeLLMClient(scripted_responses=fanout_script(n + 3)))

    return make


@pytest.fixture
def codeact_replies() -> Callable[..., list[LLMResponse]]:
    """The scripted replies a CodeAct run consumes, for record/replay tests."""
    return codeact_script


# ---------------------------------------------------------------------------
# Golden-trajectory fixture
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--golden-update",
        action="store_true",
        default=False,
        help="Re-record golden trajectory files instead of asserting against them.",
    )


def _slug(name: str) -> str:
    """Test node name -> filename. Parametrised ids keep their distinguishing part."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


@pytest.fixture
def golden_trajectory(request: pytest.FixtureRequest):
    """Run an agent and assert its trajectory matches the committed golden.

    Usage::

        async def test_run(golden_trajectory, codeact_agent):
            agent = codeact_agent()
            await golden_trajectory(agent, agent.run("compute 2+2"))
    """
    update = bool(request.config.getoption("--golden-update")) or bool(
        os.environ.get("GOLDEN_UPDATE")
    )
    path = GOLDEN_DIR / f"{_slug(request.node.name)}.json"

    async def run(
        agent: Any,
        awaitable: Awaitable[Any],
        *,
        token_tolerance: float = 0.0,
        compare_content: bool = True,
        sort_subagents: bool = True,
    ) -> None:
        trajectory = await capture(agent, awaitable)
        actual = normalize(trajectory, sort_subagents=sort_subagents)
        check(
            path,
            actual,
            update=update,
            token_tolerance=token_tolerance,
            compare_content=compare_content,
        )

    return run
