# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Golden-trajectory regression testing for NOOA agents.

Behavioural regression testing: capture an agent run as an ATIF trajectory,
normalise away everything that varies between two identical runs, and compare
it against a committed golden file. A prompt edit, a model swap, or a strategy
change that alters *how* the agent worked shows up as a diff even when the
final answer is unchanged.

Four pure functions plus a capture helper:

- :func:`capture`   — run an agent inside ``atif_scope`` and return the ``Trajectory``.
- :func:`normalize` — ``Trajectory`` -> stable dict, safe to compare and to commit.
- :func:`shape`     — normalised dict -> :class:`Shape`, the assertion surface.
- :func:`diff`      — two shapes -> list of :class:`Delta`.
- :func:`render`    — two normalised dicts -> unified diff, for the failure message.

The split between ``shape`` and the normalised dict is deliberate. Asserting on
the full dict makes every whitespace change in a model reply a test failure;
asserting on the shape keeps the failure message legible ("step count 6 -> 8")
while the committed file still carries the detail for whoever investigates.

The volatile-field list below was derived by running identical agents twice and
diffing the output, not by reading the schema — the schema says which fields
exist, not which ones are stable.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import tempfile
from collections.abc import Awaitable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from nooa.atif import Trajectory, atif_scope

__all__ = [
    "VOLATILE_FIELDS",
    "Delta",
    "GoldenMismatch",
    "Shape",
    "capture",
    "check",
    "diff",
    "dumps",
    "normalize",
    "render",
    "shape",
]


# Fields that differ between two byte-identical runs. Every entry here was
# observed in a real diff:
#   session_id / trajectory_id  — fresh per run (timestamp+uuid, uuid4)
#   timestamp                   — wall clock, on every step
#   generation_id               — uuid4 per generation, under step.extra
#   cost_usd / total_cost_usd   — varies with live pricing
# Plus object-repr addresses inside message text — see `_ADDRESS` below.
# `schema_version` is deliberately NOT scrubbed: an ATIF version bump must
# invalidate goldens loudly rather than silently reshaping the diff.
VOLATILE_FIELDS: tuple[str, ...] = (
    "session_id",
    "trajectory_id",
    "timestamp",
    "generation_id",
    "cost_usd",
    "total_cost_usd",
)

_SUBAGENTS = "subagent_trajectories"


class GoldenMismatch(AssertionError):
    """Raised when a captured trajectory does not match its golden file."""


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


async def capture(agent: Any, awaitable: Awaitable[Any]) -> Trajectory:
    """Run ``awaitable`` under ATIF export and return the resulting trajectory.

    Thin wrapper over :func:`nooa.atif.atif_scope`, which always writes a file.
    Left to its default that file lands in ``./logs/atif/`` — a test suite
    would silently accumulate one per run in the working tree — so the scope is
    pointed at a temp directory and the in-memory ``Trajectory`` is read
    instead. Capturing leaves nothing behind.

    A raising ``awaitable`` still produces a trajectory (``atif_scope`` records
    ``extra.crashed`` before re-raising) but the exception propagates; catch it
    in the caller if a crash is the expected outcome.

    Structural validity is guaranteed: ``get_trajectory()`` constructs a
    Pydantic ``Trajectory``, so its validators have already run. The ATIF
    normative rules (step-id sequencing, joinability) are the exporter's
    contract and are covered by the framework's own suite; re-asserting them
    here would couple this package to ``tests/atif``, and a violation would
    show up in the golden diff anyway.
    """
    with tempfile.TemporaryDirectory(prefix="nooa-capture-") as tmp:
        async with atif_scope(agent, path=Path(tmp) / "trajectory.json") as exporter:
            await awaitable
            return exporter.get_trajectory()


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def normalize(traj: Trajectory | dict[str, Any], *, sort_subagents: bool = True) -> dict[str, Any]:
    """Reduce a trajectory to a form that is stable across identical runs.

    Scrubs :data:`VOLATILE_FIELDS`, renumbers tool-call ids to ``call_1``,
    ``call_2``, ... (preserving the observation join rather than deleting it),
    drops emptied ``extra`` maps, and recurses into embedded subagent
    trajectories.

    ``sort_subagents`` orders ``subagent_trajectories`` by content instead of
    by arrival. Fan-out via ``asyncio.gather`` completes in nondeterministic
    order, so without this a five-way fan-out produces a different golden on
    every run. The ceiling: it also hides a *meaningful* reordering of
    subagents. With gather, order is not meaningful by construction — set it
    False for a pipeline where sequence carries information.
    """
    d = traj.model_dump(mode="json", exclude_none=True) if isinstance(traj, Trajectory) else traj
    return _normalize_one(json.loads(json.dumps(d)), sort_subagents)


def _normalize_one(d: dict[str, Any], sort_subagents: bool) -> dict[str, Any]:
    _scrub(d)
    _renumber_call_ids(d)
    subs = d.get(_SUBAGENTS)
    if subs:
        normalised = [_normalize_one(s, sort_subagents) for s in subs]
        if sort_subagents:
            normalised.sort(key=lambda s: json.dumps(s, sort_keys=True))
        d[_SUBAGENTS] = normalised
    return d


def _scrub(node: Any) -> None:
    """Recursively delete volatile keys and mask volatile text, stopping at
    subagent boundaries."""
    if isinstance(node, dict):
        for key in VOLATILE_FIELDS:
            node.pop(key, None)
        for key, value in list(node.items()):
            if key == _SUBAGENTS:
                continue  # handled by the caller's recursion
            if isinstance(value, str):
                node[key] = _mask(value)
            else:
                _scrub(value)
                if key == "extra" and value == {}:
                    del node[key]
    elif isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, str):
                node[i] = _mask(item)
            else:
                _scrub(item)


# Object reprs reach the model: NOOA renders the execution context into the
# system prompt, so anything in scope without a __repr__ arrives as
# "<function f at 0x7f3c...>". The address changes every run.
# ponytail: a blunt regex over every string. It would also mask a genuine hex
# literal in a message — harmless, since it masks it identically on both sides.
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,16}")


def _mask(text: str) -> str:
    return _ADDRESS.sub("0xADDR", text)


def _renumber_call_ids(d: dict[str, Any]) -> None:
    """Rewrite tool-call ids to ``call_N`` in first-encounter order.

    Real providers emit random ids; the join between ``tool_calls[i]`` and
    ``observation.results[j].source_call_id`` is what matters, so renumber
    rather than delete.
    """
    mapping: dict[str, str] = {}

    def rename(raw: str) -> str:
        if raw not in mapping:
            mapping[raw] = f"call_{len(mapping) + 1}"
        return mapping[raw]

    for step in d.get("steps", []):
        for call in step.get("tool_calls") or []:
            if "tool_call_id" in call:
                call["tool_call_id"] = rename(call["tool_call_id"])
        observation = step.get("observation") or {}
        for result in observation.get("results", []):
            if result.get("source_call_id") is not None:
                result["source_call_id"] = rename(result["source_call_id"])


def dumps(normalised: dict[str, Any]) -> str:
    """Serialise a normalised trajectory for committing to git."""
    return json.dumps(normalised, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """The assertion surface: what the agent did, stripped of what it said."""

    step_count: int
    sources: tuple[str, ...]
    llm_calls: int
    functions: tuple[str, ...]
    subagents: tuple[str, ...]
    crashed: bool
    prompt_tokens: int
    completion_tokens: int
    content_hash: str


# Fields compared with a relative tolerance rather than for equality.
_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens")

# Catches changes the structural fields miss — a different computed result, an
# edited message — while the rendered diff shows what actually moved. Compared
# only when `compare_content` is on, which is wrong against a live model where
# message text is sampling noise.
_CONTENT_FIELD = "content_hash"


def shape(normalised: dict[str, Any]) -> Shape:
    """Extract the comparable shape from a normalised trajectory."""
    steps = normalised.get("steps", [])
    functions: list[str] = []
    llm_calls = 0
    for step in steps:
        llm_calls += step.get("llm_call_count") or 0
        for call in step.get("tool_calls") or []:
            functions.append(call.get("function_name", "?"))

    metrics = normalised.get("final_metrics") or {}
    prompt = metrics.get("total_prompt_tokens")
    completion = metrics.get("total_completion_tokens")
    if prompt is None or completion is None:
        prompt, completion = _sum_step_tokens(steps)

    return Shape(
        step_count=len(steps),
        sources=tuple(s.get("source", "?") for s in steps),
        llm_calls=llm_calls,
        functions=tuple(functions),
        subagents=tuple(sorted(_subagent_names(normalised))),
        crashed=bool((normalised.get("extra") or {}).get("crashed", False)),
        prompt_tokens=prompt,
        completion_tokens=completion,
        content_hash=hashlib.sha256(dumps(normalised).encode()).hexdigest()[:12],
    )


def _sum_step_tokens(steps: list[dict[str, Any]]) -> tuple[int, int]:
    prompt = completion = 0
    for step in steps:
        m = step.get("metrics") or {}
        prompt += m.get("prompt_tokens") or 0
        completion += m.get("completion_tokens") or 0
    return prompt, completion


def _subagent_names(node: dict[str, Any]) -> list[str]:
    """Flattened agent names of every embedded subagent, at any depth."""
    names: list[str] = []
    for child in node.get(_SUBAGENTS) or []:
        names.append((child.get("agent") or {}).get("name", "?"))
        names.extend(_subagent_names(child))
    return names


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Delta:
    """One behavioural difference between a golden shape and an actual one."""

    field: str
    golden: Any
    actual: Any

    def __str__(self) -> str:
        return f"{self.field}: {self.golden!r} -> {self.actual!r}"


def diff(
    golden: Shape,
    actual: Shape,
    *,
    token_tolerance: float = 0.0,
    compare_content: bool = True,
) -> list[Delta]:
    """Compare two shapes. Empty list means no behavioural change.

    ``token_tolerance`` is a relative band on the token counts: 0.0 for frozen
    replay where equality is achievable, something like 0.15 against a live
    model where sampling makes exact counts meaningless.

    ``compare_content`` compares a hash of the whole normalised trajectory, so
    a change in a computed value or an edited message fails even when the step
    structure is untouched. Right for frozen replay, wrong against a live
    model — turn it off there and rely on the structural fields.
    """
    deltas: list[Delta] = []
    for f in fields(Shape):
        if f.name == _CONTENT_FIELD and not compare_content:
            continue
        want, got = getattr(golden, f.name), getattr(actual, f.name)
        if f.name in _TOKEN_FIELDS and token_tolerance > 0 and _within(want, got, token_tolerance):
            continue
        if want != got:
            deltas.append(Delta(f.name, want, got))
    # The hash says only "something changed"; the structural fields say what.
    deltas.sort(key=lambda d: d.field == _CONTENT_FIELD)
    return deltas


def _within(golden: int, actual: int, tolerance: float) -> bool:
    if golden == 0:
        return actual == 0
    return abs(actual - golden) / golden <= tolerance


def render(golden: dict[str, Any], actual: dict[str, Any], *, context: int = 3) -> str:
    """Unified diff of two normalised trajectories, for the failure message."""
    return "\n".join(
        difflib.unified_diff(
            dumps(golden).splitlines(),
            dumps(actual).splitlines(),
            fromfile="golden",
            tofile="actual",
            lineterm="",
            n=context,
        )
    )


# ---------------------------------------------------------------------------
# golden-file check
# ---------------------------------------------------------------------------


def check(
    path: Path,
    actual: dict[str, Any],
    *,
    update: bool = False,
    token_tolerance: float = 0.0,
    compare_content: bool = True,
) -> None:
    """Compare a normalised trajectory against its golden file.

    Raises :class:`GoldenMismatch` on a behavioural difference, or when the
    golden file is missing. A missing golden is a failure rather than an
    auto-create: a test that has never asserted anything would otherwise sit
    green in CI forever.
    """
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        before = path.read_text(encoding="utf-8") if existed else ""
        after = dumps(actual)
        path.write_text(after, encoding="utf-8")
        if existed and before != after:
            print(f"\nupdated golden: {path}\n{render(json.loads(before), actual)}")
        return

    if not path.exists():
        raise GoldenMismatch(
            f"no golden file at {path}\nrecord it with: pytest --golden-update -k <test name>"
        )

    golden = json.loads(path.read_text(encoding="utf-8"))

    want_version = golden.get("schema_version")
    got_version = actual.get("schema_version")
    if want_version != got_version:
        raise GoldenMismatch(
            f"golden recorded under {want_version}, running {got_version} — "
            f"re-record with: pytest --golden-update"
        )

    deltas = diff(
        shape(golden),
        shape(actual),
        token_tolerance=token_tolerance,
        compare_content=compare_content,
    )
    if not deltas:
        return

    summary = "\n".join(f"  {d}" for d in deltas)
    raise GoldenMismatch(
        f"agent behaviour changed ({len(deltas)} difference(s)):\n{summary}\n\n"
        f"{render(golden, actual)}\n\n"
        f"if this change is intended: pytest --golden-update"
    )
