# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Record/replay round-trip for frozen mode.

A ``FakeLLMClient`` stands in for the real model here — what is under test is
that whatever the inner client returns survives a save/load cycle and
reproduces the same trajectory, not that any particular provider works.
"""

from __future__ import annotations

import pytest
from nooa_bench.recording import (
    RecordingLLM,
    ScriptExhausted,
    dump_script,
    load_model,
    load_script,
    replay,
)
from nooa_bench.trajectory import capture, dumps, normalize

from nooa.errors import GenerationError
from nooa.unifiedllm import FakeLLMClient


async def test_recorded_script_reproduces_the_trajectory(tmp_path, codeact_agent, codeact_replies):
    """Record once, replay, and get a byte-identical normalised trajectory."""
    script = tmp_path / "run.llm.json"

    recorder = RecordingLLM(FakeLLMClient(scripted_responses=codeact_replies(3)))
    recorded_agent = codeact_agent(llm=recorder)
    live = await capture(recorded_agent, recorded_agent.run("compute 2+2"))
    recorder.save(script)
    assert len(recorder.responses) == 3

    frozen_agent = codeact_agent(llm=replay(script))
    frozen = await capture(frozen_agent, frozen_agent.run("compute 2+2"))

    assert dumps(normalize(live)) == dumps(normalize(frozen))


async def test_replay_survives_repetition(tmp_path, codeact_agent, codeact_replies):
    """Twenty replays, no network, identical every time."""
    script = tmp_path / "run.llm.json"
    recorder = RecordingLLM(FakeLLMClient(scripted_responses=codeact_replies(3)))
    agent = codeact_agent(llm=recorder)
    await capture(agent, agent.run("compute 2+2"))
    recorder.save(script)

    seen = set()
    for _ in range(20):
        replayed = codeact_agent(llm=replay(script))
        seen.add(dumps(normalize(await capture(replayed, replayed.run("compute 2+2")))))
    assert len(seen) == 1


def test_script_round_trips_through_json(tmp_path, codeact_replies):
    script = tmp_path / "run.llm.json"
    original = codeact_replies(3)
    dump_script(original, script)

    loaded = load_script(script)
    assert len(loaded) == len(original)
    for before, after in zip(original, loaded, strict=True):
        assert after.content == before.content
        assert after.finish_reason == before.finish_reason
        assert after.usage == before.usage
        assert [(c.id, c.name, c.arguments) for c in after.tool_calls] == [
            (c.id, c.name, c.arguments) for c in before.tool_calls
        ]


def test_script_carries_the_recorded_model_name(tmp_path, codeact_replies):
    """A replay must report the model it was recorded against.

    NOOA copies the client's model into every agent step as ``model_name``, and
    ``FakeLLMClient`` calls itself ``fake-model`` — so a script that does not
    carry the name forward produces a replayed trajectory differing from the
    recording on exactly that line. Found only by recording against a real
    provider; this test keeps it from coming back without one.
    """
    script = tmp_path / "run.llm.json"
    inner = FakeLLMClient(scripted_responses=codeact_replies(1))
    inner.model = "ollama_chat/qwen2.5:1.5b"

    recorder = RecordingLLM(inner)
    recorder.responses.extend(codeact_replies(1))
    recorder.save(script)

    assert load_model(script) == "ollama_chat/qwen2.5:1.5b"
    assert replay(script).model == "ollama_chat/qwen2.5:1.5b"


def test_replay_falls_back_when_no_model_was_recorded(tmp_path, codeact_replies):
    """Scripts written before the model field existed must still load."""
    script = tmp_path / "old.llm.json"
    dump_script(codeact_replies(1), script)  # no model= argument
    assert load_model(script) is None
    assert replay(script).model == "fake-model"


def test_raw_response_is_not_persisted(tmp_path, codeact_replies):
    """Provider objects are not portable and nothing downstream reads them."""
    script = tmp_path / "run.llm.json"
    original = codeact_replies(1)
    original[0].raw_response = object()  # would not survive json.dumps
    dump_script(original, script)
    assert load_script(script)[0].raw_response is None


async def test_extra_model_call_raises_instead_of_padding(tmp_path, codeact_agent, codeact_replies):
    """An agent asking for more replies than were recorded is the regression
    this harness exists to catch, so it must not fail soft.

    ``CodeActStrategy`` treats any client exception as a transient API error:
    it retries three times and re-raises as ``GenerationError``. The wrapper is
    unavoidable from here, but the message survives it, which is what the
    person reading the CI log needs.
    """
    script = tmp_path / "short.llm.json"
    dump_script(codeact_replies(3)[:1], script)  # one reply; the agent needs three

    agent = codeact_agent(llm=replay(script))
    with pytest.raises((ScriptExhausted, GenerationError), match="more model calls"):
        await capture(agent, agent.run("compute 2+2"))
