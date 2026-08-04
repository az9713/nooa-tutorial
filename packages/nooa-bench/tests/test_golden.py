# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Golden-trajectory regression tests — the fixture used as intended.

These are frozen-mode tests: the LLM is a ``FakeLLMClient`` replaying a fixed
script, so the run is deterministic and needs no API key or network. They
catch regressions in *our* code — strategy plumbing, context assembly, method
dispatch, step accounting — not in model behaviour. A live-model equivalent
belongs under the repo's existing ``integration`` marker.

Re-record after an intended change::

    pytest packages/nooa-bench/tests --golden-update
"""

from __future__ import annotations


async def test_codeact_three_turn_run(golden_trajectory, codeact_agent):
    """A three-turn CodeAct run: two executions then a return."""
    agent = codeact_agent(turns=3)
    await golden_trajectory(agent, agent.run("compute 2+2"))


async def test_codeact_single_turn_run(golden_trajectory, codeact_agent):
    """The same agent doing less work — a distinct, separately-tracked shape."""
    agent = codeact_agent(turns=1)
    await golden_trajectory(agent, agent.run("compute 2+2"))


async def test_fanout_over_five_items(golden_trajectory, fanout_agent):
    """Five concurrent generations under one deterministic parent method."""
    agent = fanout_agent(5)
    await golden_trajectory(agent, agent.run_all([f"item-{i}" for i in range(5)]))
