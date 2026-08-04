# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fixture agents for the golden-trajectory tests.

**Keep this module's namespace small and stable.** NOOA renders the execution
context — the module globals visible to the agent — into the system prompt, so
every name defined here reaches the model and lands in the recorded
trajectory. Adding an unrelated helper to this file invalidates every golden.
That is why these agents do not live in ``conftest.py``: test scaffolding
accumulates there, and each addition would force a re-record.

Deliberately built on ``CodeActStrategy`` and ``PredictStrategy`` rather than
``CodeActLiteStrategy`` / ``ReflexionStrategy``: those two are gated behind a
``FutureWarning`` and re-exported lazily through ``nooa.experimental``, so a
golden recorded against them would sit on an unstable API.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nooa import Agent, strategy
from nooa.config import CodeActConfig
from nooa.strategies import CodeActStrategy, PredictStrategy
from nooa.unifiedllm import FakeLLMClient, LLMResponse, ToolCall

_DEFAULT_LLM = FakeLLMClient()


def response(
    content: str = "",
    tool_calls: list[ToolCall] | None = None,
    *,
    usage: dict[str, int] | None = None,
) -> LLMResponse:
    """A scripted assistant reply."""
    return LLMResponse(
        raw_response=None,
        content=content,
        tool_calls=tool_calls or [],
        finish_reason="tool_calls" if tool_calls else "stop",
        assistant_message={"role": "assistant", "content": content},
        usage=usage or {"prompt_tokens": 50, "completion_tokens": 10},
    )


def exec_call(code: str, call_id: str) -> ToolCall:
    """An ``execute_python`` tool call."""
    return ToolCall(id=call_id, name="execute_python", arguments=json.dumps({"code": code}))


def return_call(result: Any, call_id: str) -> ToolCall:
    """A ``return_result`` tool call."""
    return ToolCall(id=call_id, name="return_result", arguments=json.dumps({"result": result}))


def codeact_script(turns: int = 3) -> list[LLMResponse]:
    """``turns`` CodeAct iterations: compute, compute, ..., return."""
    middle = [
        response(content=f"Step {i}.", tool_calls=[exec_call(f"x{i} = {i} + 1", f"call_{i}")])
        for i in range(1, turns)
    ]
    return [*middle, response(content="Done.", tool_calls=[return_call(4, "call_ret")])]


def fanout_script(n: int) -> list[LLMResponse]:
    """``PredictStrategy`` parses the reply as structured output, so: JSON."""
    return [response(content=json.dumps(f"cat{i}")) for i in range(n)]


class CodeActAgent(Agent, llm=_DEFAULT_LLM):
    """Minimal CodeAct agent."""

    @strategy(CodeActStrategy(config=CodeActConfig(max_iterations=5)))
    async def run(self, prompt: str) -> int:
        """Solve {prompt}."""
        ...


@strategy(PredictStrategy())
async def classify(item: str) -> str:
    """Classify {item} into a category."""
    ...


class FanOutAgent(Agent, llm=_DEFAULT_LLM):
    """Deterministic parent that fans out to a generated helper.

    ``run_all`` has a real body, so it is plain Python; each ``classify`` call
    is its own generation and lands as an embedded subagent trajectory.
    ``asyncio.gather`` means they complete out of order, which is what makes
    this the interesting case for the normaliser. Standalone ``@strategy``
    functions resolve their LLM by cascading from the calling agent
    (``src/nooa/standalone.py:161``), so ``classify`` needs no client.
    """

    async def run_all(self, items: list[str]) -> list[str]:
        """Classify every item concurrently."""
        return await asyncio.gather(*(classify(item) for item in items))
