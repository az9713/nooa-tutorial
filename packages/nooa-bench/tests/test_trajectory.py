# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the trajectory normaliser, shape extractor and differ.

The tests that carry weight are the negative ones: two runs that differ only
in volatile fields must produce zero deltas, and a run with one extra step
must produce a delta that names the step count.
"""

from __future__ import annotations

import json

import pytest
from nooa_bench.trajectory import (
    Delta,
    GoldenMismatch,
    capture,
    check,
    diff,
    dumps,
    normalize,
    render,
    shape,
)

# ---------------------------------------------------------------------------
# Hand-built trajectories — cheap, and they isolate one behaviour each
# ---------------------------------------------------------------------------


def _traj(steps: list[dict], **root) -> dict:
    return {
        "schema_version": "ATIF-v1.7",
        "session_id": "20260803T120000-deadbeef",
        "trajectory_id": "11111111-2222-3333-4444-555555555555",
        "agent": {"name": "T", "version": "0.0.0"},
        "steps": steps,
        **root,
    }


def _step(step_id: int, source: str = "agent", **kw) -> dict:
    return {
        "step_id": step_id,
        "source": source,
        "message": "m",
        "timestamp": f"2026-08-03T12:00:0{step_id}.000Z",
        "extra": {"generation_id": f"gen-{step_id}"},
        **kw,
    }


def test_volatile_fields_are_scrubbed():
    a = normalize(_traj([_step(1)]))
    assert "session_id" not in a
    assert "trajectory_id" not in a
    assert "timestamp" not in a["steps"][0]
    # `extra` held only a generation_id, so it goes entirely.
    assert "extra" not in a["steps"][0]
    # But the version stays: a schema bump must invalidate goldens loudly.
    assert a["schema_version"] == "ATIF-v1.7"


def test_only_volatile_differences_produce_no_deltas():
    """The central claim. Two runs, different clocks and uuids, same behaviour."""
    run1 = _traj([_step(1), _step(2)])
    run2 = json.loads(json.dumps(run1))
    run2["session_id"] = "20260803T130000-cafebabe"
    run2["trajectory_id"] = "99999999-8888-7777-6666-555555555555"
    run2["steps"][0]["timestamp"] = "2026-08-03T13:00:01.123Z"
    run2["steps"][1]["extra"]["generation_id"] = "gen-other"

    assert normalize(run1) == normalize(run2)
    assert diff(shape(normalize(run1)), shape(normalize(run2))) == []


def test_one_extra_step_is_reported():
    golden = shape(normalize(_traj([_step(1), _step(2)])))
    actual = shape(normalize(_traj([_step(1), _step(2), _step(3)])))
    deltas = diff(golden, actual)
    assert Delta("step_count", 2, 3) in deltas


def test_tool_call_ids_are_renumbered_but_the_join_survives():
    step = _step(
        1,
        tool_calls=[
            {"tool_call_id": "toolu_xyz", "function_name": "execute_python", "arguments": {}},
            {"tool_call_id": "toolu_abc", "function_name": "return_result", "arguments": {}},
        ],
        observation={
            "results": [
                {"source_call_id": "toolu_abc", "content": "second"},
                {"source_call_id": "toolu_xyz", "content": "first"},
            ]
        },
    )
    out = normalize(_traj([step]))["steps"][0]
    assert [c["tool_call_id"] for c in out["tool_calls"]] == ["call_1", "call_2"]
    # The observation still points at the right calls, by content.
    joined = {r["source_call_id"]: r["content"] for r in out["observation"]["results"]}
    assert joined == {"call_1": "first", "call_2": "second"}


def test_provider_id_churn_alone_is_not_a_regression():
    a = _traj(
        [_step(1, tool_calls=[{"tool_call_id": "id_1", "function_name": "f", "arguments": {}}])]
    )
    b = _traj(
        [_step(1, tool_calls=[{"tool_call_id": "id_2", "function_name": "f", "arguments": {}}])]
    )
    assert normalize(a) == normalize(b)


def test_subagents_are_sorted_by_content():
    child_a = _traj([_step(1)], agent={"name": "classify", "version": "0"})
    child_b = _traj([_step(1, message="different")], agent={"name": "classify", "version": "0"})
    forward = normalize(_traj([], subagent_trajectories=[child_a, child_b]))
    backward = normalize(_traj([], subagent_trajectories=[child_b, child_a]))
    assert forward == backward


def test_subagent_sorting_can_be_turned_off():
    child_a = _traj([_step(1, message="a")], agent={"name": "s", "version": "0"})
    child_b = _traj([_step(1, message="b")], agent={"name": "s", "version": "0"})
    forward = normalize(_traj([], subagent_trajectories=[child_a, child_b]), sort_subagents=False)
    backward = normalize(_traj([], subagent_trajectories=[child_b, child_a]), sort_subagents=False)
    assert forward != backward


def test_shape_reads_tokens_from_final_metrics():
    t = _traj([_step(1)], final_metrics={"total_prompt_tokens": 90, "total_completion_tokens": 12})
    s = shape(normalize(t))
    assert (s.prompt_tokens, s.completion_tokens) == (90, 12)


def test_shape_falls_back_to_summing_step_metrics():
    steps = [
        _step(1, metrics={"prompt_tokens": 10, "completion_tokens": 2}),
        _step(2, metrics={"prompt_tokens": 20, "completion_tokens": 3}),
    ]
    s = shape(normalize(_traj(steps)))
    assert (s.prompt_tokens, s.completion_tokens) == (30, 5)


def test_token_tolerance_bands_live_noise():
    """Token banding is a live-mode concern, so content comparison is off —
    the metrics themselves are part of the content."""
    base = _traj(
        [_step(1)], final_metrics={"total_prompt_tokens": 100, "total_completion_tokens": 10}
    )
    noisy = _traj(
        [_step(1)], final_metrics={"total_prompt_tokens": 110, "total_completion_tokens": 10}
    )
    golden, actual = shape(normalize(base)), shape(normalize(noisy))
    assert diff(golden, actual, compare_content=False) != []  # frozen: exact
    assert diff(golden, actual, token_tolerance=0.15, compare_content=False) == []  # live: banded


def test_zero_token_golden_requires_zero():
    base = _traj([_step(1)], final_metrics={"total_prompt_tokens": 0, "total_completion_tokens": 0})
    actual = _traj(
        [_step(1)], final_metrics={"total_prompt_tokens": 5, "total_completion_tokens": 0}
    )
    deltas = diff(
        shape(normalize(base)),
        shape(normalize(actual)),
        token_tolerance=0.5,
        compare_content=False,
    )
    assert [d.field for d in deltas] == ["prompt_tokens"]


def test_object_addresses_in_prompts_are_masked():
    """NOOA renders the execution context into the system prompt, so object
    reprs — and their memory addresses — reach the trajectory."""
    a = _traj([_step(1, message="in scope: <function f at 0x78289b0c5d00>")])
    b = _traj([_step(1, message="in scope: <function f at 0x74d8069e9c60>")])
    assert normalize(a) == normalize(b)
    assert "0xADDR" in normalize(a)["steps"][0]["message"]


def test_content_change_with_identical_structure_is_caught():
    """Same steps, different computed value. The structural fields cannot see
    this, so the content hash has to — otherwise a stale golden sits green."""
    before = normalize(_traj([_step(1, message="result: 4")]))
    after = normalize(_traj([_step(1, message="result: 5")]))
    structural = [d for d in diff(shape(before), shape(after)) if d.field != "content_hash"]
    assert structural == []
    assert [d.field for d in diff(shape(before), shape(after))] == ["content_hash"]


def test_content_comparison_is_off_against_a_live_model():
    """Message text is sampling noise live; only structure should be asserted."""
    before = normalize(_traj([_step(1, message="Sure, let me compute that.")]))
    after = normalize(_traj([_step(1, message="I'll work that out.")]))
    assert diff(shape(before), shape(after), compare_content=False) == []


def test_structural_change_is_reported_before_the_hash():
    """The hash says 'something moved'; the named fields say what. Order matters
    because the first line of the failure message is the one that gets read."""
    before = shape(normalize(_traj([_step(1)])))
    after = shape(normalize(_traj([_step(1), _step(2)])))
    assert [d.field for d in diff(before, after)][-1] == "content_hash"


def test_crash_is_part_of_the_shape():
    ok = shape(normalize(_traj([_step(1)])))
    crashed = shape(normalize(_traj([_step(1)], extra={"crashed": True})))
    assert ok.crashed is False and crashed.crashed is True
    assert Delta("crashed", False, True) in diff(ok, crashed)


def test_render_produces_a_readable_diff():
    a = normalize(_traj([_step(1)]))
    b = normalize(_traj([_step(1, message="changed")]))
    out = render(a, b)
    assert '-      "message": "m"' in out
    assert '+      "message": "changed"' in out


# ---------------------------------------------------------------------------
# Golden-file behaviour
# ---------------------------------------------------------------------------


def test_missing_golden_fails_rather_than_auto_creating(tmp_path):
    with pytest.raises(GoldenMismatch, match="no golden file"):
        check(tmp_path / "absent.json", normalize(_traj([_step(1)])))
    assert not (tmp_path / "absent.json").exists()


def test_update_writes_the_golden(tmp_path):
    path = tmp_path / "g.json"
    actual = normalize(_traj([_step(1)]))
    check(path, actual, update=True)
    assert json.loads(path.read_text()) == actual
    check(path, actual)  # now passes


def test_schema_bump_asks_for_a_re_record(tmp_path):
    path = tmp_path / "g.json"
    check(path, normalize(_traj([_step(1)])), update=True)
    future = normalize(_traj([_step(1)]))
    future["schema_version"] = "ATIF-v1.8"
    with pytest.raises(GoldenMismatch, match="re-record"):
        check(path, future)


def test_mismatch_message_names_the_change(tmp_path):
    path = tmp_path / "g.json"
    check(path, normalize(_traj([_step(1)])), update=True)
    with pytest.raises(GoldenMismatch) as exc:
        check(path, normalize(_traj([_step(1), _step(2)])))
    assert "step_count: 1 -> 2" in str(exc.value)


def test_dumps_is_stable_and_newline_terminated():
    out = dumps(normalize(_traj([_step(1)])))
    assert out.endswith("\n")
    assert out == dumps(json.loads(out))


# ---------------------------------------------------------------------------
# Stability against real agent runs — phase 2's acceptance check
# ---------------------------------------------------------------------------


async def _run_codeact(codeact_agent, turns: int = 3):
    agent = codeact_agent(turns)
    return await capture(agent, agent.run("compute 2+2"))


async def _run_fanout(fanout_agent, n: int = 5):
    agent = fanout_agent(n)
    return await capture(agent, agent.run_all([f"item-{i}" for i in range(n)]))


async def test_identical_codeact_runs_normalise_identically(codeact_agent):
    """Two runs of the same stubbed agent produce byte-identical output.

    Before normalisation these differ on 20 of 135 lines — see the phase-1
    spike in the plan.
    """
    first = normalize(await _run_codeact(codeact_agent))
    second = normalize(await _run_codeact(codeact_agent))
    assert dumps(first) == dumps(second)


async def test_capture_leaves_nothing_in_the_working_tree(codeact_agent, tmp_path, monkeypatch):
    """``atif_scope`` writes a file per run. Left at its default that is
    ``./logs/atif/`` in whatever directory pytest was started from, so a suite
    would quietly accumulate hundreds of them."""
    monkeypatch.chdir(tmp_path)
    await _run_codeact(codeact_agent)
    assert list(tmp_path.iterdir()) == []


async def test_fanout_ordering_does_not_leak_into_the_golden(fanout_agent):
    """asyncio.gather completes out of order; the normalised form must not."""
    first = normalize(await _run_fanout(fanout_agent))
    second = normalize(await _run_fanout(fanout_agent))
    assert dumps(first) == dumps(second)
    assert shape(first).subagents == ("classify",) * 5


async def test_a_real_behavioural_change_is_still_visible(codeact_agent):
    """Sanity: the normaliser is not so aggressive that it hides everything."""
    two_turns = normalize(await _run_codeact(codeact_agent, turns=2))
    three_turns = normalize(await _run_codeact(codeact_agent, turns=3))
    deltas = diff(shape(two_turns), shape(three_turns))
    assert "step_count" in {d.field for d in deltas}
