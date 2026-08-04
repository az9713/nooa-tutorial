# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Record model replies once, replay them forever — frozen mode.

A golden trajectory recorded against a live model is only reproducible if the
model's replies are reproducible. Wrap the real client in :class:`RecordingLLM`
for one run, save the script, and every later run replays it with no network
and no API key. The agent still executes for real: strategies, context
assembly, method dispatch, the REPL, and tracing all run. Only the model is
frozen.

What that buys, and what it costs:

- **Detects** regressions in your own code — a refactor that doubles the step
  count, a strategy change that drops an observation, a context-assembly edit
  that reshapes the prompt.
- **Cannot detect** anything requiring the model to react. Edit a prompt and
  the recorded reply comes back unchanged. Prompt-quality regressions need a
  live run; see the ``integration`` marker in the repo's pytest config.

Usage::

    # once, against a real model, in a sandbox:
    llm = RecordingLLM(LiteLLMClient(model="..."))
    agent = MyAgent(llm=llm)
    await agent.run(...)
    llm.save(Path("tests/golden/my_test.llm.json"))

    # thereafter, in CI:
    agent = MyAgent(llm=replay(Path("tests/golden/my_test.llm.json")))
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nooa.unifiedllm import FakeLLMClient, LLMResponse, ToolCall

__all__ = [
    "RecordingLLM",
    "ScriptExhausted",
    "dump_script",
    "load_model",
    "load_script",
    "replay",
]


class ScriptExhausted(RuntimeError):
    """The agent asked for more model replies than were recorded."""


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _to_json(response: LLMResponse) -> dict[str, Any]:
    """Serialise the fields replay needs.

    ``raw_response`` is deliberately dropped: it is the provider's own object,
    is not portable, and nothing downstream of a replay reads it.
    """
    content = response.content
    return {
        "content": content if isinstance(content, str) else content.model_dump_json(),
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls
        ],
        "finish_reason": response.finish_reason,
        "assistant_message": response.assistant_message,
        "reasoning": response.reasoning,
        "usage": response.usage,
    }


def _from_json(d: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        raw_response=None,
        content=d["content"],
        tool_calls=[
            ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"]) for c in d["tool_calls"]
        ],
        finish_reason=d["finish_reason"],
        assistant_message=d["assistant_message"],
        reasoning=d.get("reasoning"),
        usage=d.get("usage"),
    )


def dump_script(responses: list[LLMResponse], path: Path, *, model: str | None = None) -> None:
    """Write a recorded script next to its golden trajectory.

    ``model`` is the name the recording client reported. It is not decoration:
    NOOA writes the client's model into every agent step as ``model_name``, so
    a replay that does not carry it forward produces a trajectory that differs
    from the one just recorded — see :func:`replay`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": model, "responses": [_to_json(r) for r in responses]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_script(path: Path) -> list[LLMResponse]:
    """Read a recorded script."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_from_json(d) for d in payload["responses"]]


def load_model(path: Path) -> str | None:
    """The model name a script was recorded against, if it was stored."""
    return json.loads(path.read_text(encoding="utf-8")).get("model")


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


class RecordingLLM:
    """Pass-through wrapper that keeps every reply the inner client returns.

    Delegates everything but ``acall`` to the wrapped client, so it works with
    any :class:`nooa.unifiedllm.UnifiedLLM` without knowing its shape.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.responses: list[LLMResponse] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def acall(self, *args: Any, **kwargs: Any) -> LLMResponse:
        response = await self._inner.acall(*args, **kwargs)
        self.responses.append(response)
        return response

    def save(self, path: Path) -> None:
        """Write the recorded script. Call after the run completes."""
        dump_script(self.responses, path, model=getattr(self._inner, "model", None))


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class _StrictFake(FakeLLMClient):
    """``FakeLLMClient`` that raises instead of padding with empty replies.

    The stock fake returns an empty response once its queue runs dry. For a
    regression harness that is exactly backwards: an agent making *more* model
    calls than it did when recorded is the regression we are looking for, and
    a silent empty reply buries it inside a confusing downstream parse error.
    """

    async def acall(self, *args: Any, **kwargs: Any) -> LLMResponse:
        # Reaches into the parent's queue; a rename upstream fails loudly here
        # rather than silently restoring the fail-soft behaviour.
        if not self._response_queue:
            raise ScriptExhausted(
                f"agent requested reply #{self.call_count + 1} but the recorded script "
                f"has only {self.call_count}. The agent is making more model calls than "
                f"when this script was recorded — that is the regression. If it is "
                f"intended, re-record the script."
            )
        return await super().acall(*args, **kwargs)


def replay(path: Path) -> FakeLLMClient:
    """A client that replays a recorded script and raises when it runs out.

    Reports the model name the script was recorded against. ``FakeLLMClient``
    otherwise calls itself ``fake-model``, and NOOA copies the client's model
    into every agent step as ``model_name`` — so without this a trajectory
    replayed from a live recording differs from the recording on exactly one
    line, which is enough to fail its own golden. Found by recording against
    Ollama; invisible when the recording client is itself a fake.

    ``model_name`` is deliberately not scrubbed by the normaliser: noticing a
    model swap is a headline use of this tool.
    """
    client = _StrictFake(scripted_responses=load_script(path))
    recorded_model = load_model(path)
    if recorded_model:
        client.model = recorded_model
    return client
