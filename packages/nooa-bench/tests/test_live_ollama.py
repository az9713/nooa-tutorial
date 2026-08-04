# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Live-model tests for the golden-trajectory harness, against Ollama.

Everything else in this package runs against a stubbed client, which leaves the
interesting half untested: real providers emit random tool-call ids, report
token counts that move, return structured output as a Pydantic model rather
than a string, and — the one that actually bit — name themselves.

Deselected by default: the repo's ``addopts`` carries
``-m 'not integration and not stress'``. Run them deliberately::

    OLLAMA_API_BASE=http://localhost:11434 \\
      uv run --frozen pytest packages/nooa-bench/tests/test_live_ollama.py -m integration

Needs no API key. ``ollama pull qwen2.5:1.5b`` is about 1 GB. From WSL against
an Ollama running on the Windows host, ``OLLAMA_API_BASE`` must be the gateway
address (``ip route | grep default``), not localhost, and Ollama must have been
started with ``OLLAMA_HOST=0.0.0.0``.

No goldens are committed for these. A live model is not reproducible enough to
diff against a file checked in weeks ago; what is asserted is that two runs
agree with each other under live settings, and that a recording replays
faithfully.
"""

from __future__ import annotations

import os

import pytest
from nooa_bench.recording import RecordingLLM, replay
from nooa_bench.trajectory import capture, diff, dumps, normalize, shape

from nooa import Agent, strategy
from nooa.config import CodeActConfig
from nooa.errors import GenerationError
from nooa.strategies import CodeActStrategy, PredictStrategy
from nooa.unifiedllm import CompletionClient

pytestmark = [pytest.mark.integration, pytest.mark.provider_compat_ollama]

API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "ollama_chat/qwen2.5:1.5b")


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{API_BASE}/api/tags", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


pytestmark.append(pytest.mark.skipif(not _reachable(), reason=f"no Ollama at {API_BASE}"))


@pytest.fixture(scope="module", autouse=True)
def _allow_ollama_params():
    """NOOA sends ``parallel_tool_calls``; ``ollama_chat`` rejects it outright.

    Without this, any tool-using strategy fails against Ollama with
    ``UnsupportedParamsError`` after three retries — so "Ollama works with no
    API key" holds for generation but not for CodeAct. Setting
    ``litellm.drop_params`` is the documented escape hatch; it is set here
    rather than in the library because it is global mutable state on litellm
    and belongs to the caller, not to nooa-bench.
    """
    import litellm

    previous = litellm.drop_params
    litellm.drop_params = True
    yield
    litellm.drop_params = previous


def client():
    return CompletionClient(model=MODEL, api_base=API_BASE)


class LivePredictAgent(Agent):
    """Answer short factual questions."""

    @strategy(PredictStrategy())
    async def capital_of(self, country: str) -> str:
        """Return the capital city of {country}. One word."""
        ...


class LiveMathAgent(Agent):
    """Compute arithmetic by writing Python."""

    @strategy(CodeActStrategy(config=CodeActConfig(max_iterations=4)))
    async def compute(self, expression: str) -> int:
        """Compute {expression} and return the integer result."""
        ...


async def test_recording_replays_identically(tmp_path):
    """The whole point of frozen mode: a live run, re-run from its script,
    produces the same normalised trajectory.

    This is the regression test for a bug that only a live recording could
    expose. ``FakeLLMClient`` calls itself ``fake-model``, NOOA copies the
    client's model into every agent step, and so a replay of a live recording
    differed from the recording on exactly that one line — enough to fail its
    own golden, and invisible whenever the recording client is also a fake.
    """
    recorder = RecordingLLM(client())
    agent = LivePredictAgent(llm=recorder)
    live = normalize(await capture(agent, agent.capital_of("Japan")))

    script = tmp_path / "capital.llm.json"
    recorder.save(script)
    assert recorder.responses, "nothing recorded"

    replayed_agent = LivePredictAgent(llm=replay(script))
    frozen = normalize(await capture(replayed_agent, replayed_agent.capital_of("Japan")))

    assert dumps(live) == dumps(frozen)


async def test_two_live_runs_agree_structurally():
    """Live settings — token banding on, content comparison off — should see
    two runs of the same task as the same behaviour."""
    a = LivePredictAgent(llm=client())
    b = LivePredictAgent(llm=client())
    first = normalize(await capture(a, a.capital_of("France")))
    second = normalize(await capture(b, b.capital_of("France")))

    deltas = diff(shape(first), shape(second), token_tolerance=0.15, compare_content=False)
    assert deltas == [], f"live runs diverged structurally: {[str(d) for d in deltas]}"


async def test_real_tool_call_ids_are_renumbered(tmp_path):
    """Providers emit ids like ``call_3hfgfv2c``; the fake pins them, so this
    path is only genuinely exercised against a real model."""
    recorder = RecordingLLM(client())
    agent = LiveMathAgent(llm=recorder)
    try:
        trajectory = normalize(await capture(agent, agent.compute("17 * 23 + 5")))
    except GenerationError as exc:
        # A small local model fails this task roughly one run in three, usually
        # "return_result validation failed after 3 attempts" — it hands back
        # something that will not coerce to int. That is the model being weak,
        # not the harness being broken, and a live test that cannot tell the
        # two apart is worse than no live test. Skipping reports the frequency;
        # a rerun would hide it.
        pytest.skip(f"model could not complete the task: {str(exc)[:120]}")

    raw_ids = [c.id for r in recorder.responses for c in r.tool_calls]
    if not raw_ids:
        pytest.skip("model answered without calling a tool — nothing to renumber")
    assert not any(i.startswith("call_") and i[5:].isdigit() for i in raw_ids), (
        f"provider ids already look canonical ({raw_ids}); this test proves nothing"
    )

    normalised_ids = [
        c["tool_call_id"] for s in trajectory["steps"] for c in (s.get("tool_calls") or [])
    ]
    assert normalised_ids == [f"call_{i}" for i in range(1, len(normalised_ids) + 1)]


async def test_structured_output_survives_the_script_round_trip(tmp_path):
    """``PredictStrategy`` returns a Pydantic model as ``content``; the script
    stores it as JSON text. The strategy re-parses it on replay, so the
    trajectory is unchanged — but the two objects are not the same type, and
    that asymmetry is worth pinning."""
    recorder = RecordingLLM(client())
    agent = LivePredictAgent(llm=recorder)
    await capture(agent, agent.capital_of("Italy"))

    script = tmp_path / "italy.llm.json"
    recorder.save(script)

    from nooa_bench.recording import load_script

    original = recorder.responses[0].content
    restored = load_script(script)[0].content
    assert not isinstance(original, str), "expected a model, not text"
    assert isinstance(restored, str)
    assert restored == original.model_dump_json()
