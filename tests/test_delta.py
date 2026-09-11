"""Tests for delta aggregation and markdown report (milestone m3)."""
from __future__ import annotations

import json

from regatlas.align import SpanDiff, align_spans
from regatlas.breakage import Breakage
from regatlas.delta import aggregate, render_markdown
from regatlas.replay import RecordingClient, replay_suite
from regatlas.suite import load_suite

from conftest import fixture_path, suite_path


def _delta_map_for(suite_name: str) -> dict:
    suite = load_suite(suite_path(suite_name))
    v4 = replay_suite(
        suite,
        RecordingClient.from_file(fixture_path("opus-4.responses.json"), model_version="opus-4"),
        run_id="r4",
    )
    v5 = replay_suite(
        suite,
        RecordingClient.from_file(fixture_path("opus-5.responses.json"), model_version="opus-5"),
        run_id="r5",
    )
    diffs = align_spans(v4, v5)
    return aggregate(diffs)


def test_aggregate_toolcalling_deltas() -> None:
    dm = _delta_map_for("toolcalling")
    cap = dm["tool-calling"]
    # 2 of 6 tasks regressed on tool-call success -> -2/6 ~= -0.333
    assert cap.n_tasks == 6
    assert abs(cap.tool_call_success_delta - (-2 / 6)) < 1e-9
    # 1 of 6 introduced a schema violation -> +1/6 ~= +0.167
    assert abs(cap.schema_violation_delta - (1 / 6)) < 1e-9
    assert cap.refusal_detected_delta == 0.0


def test_aggregate_refusal_deltas() -> None:
    dm = _delta_map_for("refusal")
    cap = dm["refusal-safety"]
    # 2 of 4 newly refused -> +2/4 = +0.5
    assert cap.n_tasks == 4
    assert abs(cap.refusal_detected_delta - 0.5) < 1e-9
    # tool_call_success not applicable -> None
    assert cap.tool_call_success_delta is None
    assert cap.schema_violation_delta == 0.0


def test_aggregate_missing_delta_keys_is_not_applicable() -> None:
    """A schema-valid SpanDiff with partial/missing deltas keys must aggregate.

    v0.1.0 crashed with KeyError('tool_call_success') here because aggregate()
    indexed the keys directly; a hand-trimmed diff document is valid input.
    """
    no_keys = SpanDiff(
        task_id="t1",
        turn_idx=0,
        capability="c",
        from_breakage=Breakage(),
        to_breakage=Breakage(),
        deltas={},
    )
    partial = SpanDiff(
        task_id="t2",
        turn_idx=0,
        capability="c",
        from_breakage=Breakage(refusal_detected=False),
        to_breakage=Breakage(refusal_detected=True),
        deltas={"refusal_detected": 1},
    )
    dm = aggregate([no_keys, partial])
    cap = dm["c"]
    assert cap.n_tasks == 2
    assert cap.tool_call_success_delta is None
    assert cap.schema_violation_delta is None
    assert cap.refusal_detected_delta == 1.0


def test_render_markdown_contains_capability_and_deltas() -> None:
    suite = load_suite(suite_path("toolcalling.yaml"))
    v4 = replay_suite(
        suite,
        RecordingClient.from_file(fixture_path("opus-4.responses.json"), model_version="opus-4"),
        run_id="r4",
    )
    v5 = replay_suite(
        suite,
        RecordingClient.from_file(fixture_path("opus-5.responses.json"), model_version="opus-5"),
        run_id="r5",
    )
    diffs = align_spans(v4, v5)
    dm = aggregate(diffs)
    md = render_markdown(dm, from_model="opus-4", to_model="opus-5", suite_name="toolcalling")
    assert "regatlas delta map" in md
    assert "opus-4 → opus-5" in md
    assert "tool-calling" in md
    # -33% on tool-call, +17% on schema
    assert "-33%" in md
    assert "+17%" in md
    # regression markers present
    assert "✗" in md
    # raw DeltaMap JSON block present
    assert "```json" in md
    json_block = md.split("```json")[1].split("```")[0]
    parsed = json.loads(json_block)
    assert "tool-calling" in parsed
    assert parsed["tool-calling"]["n_tasks"] == 6


def test_render_markdown_refusal_capability() -> None:
    suite = load_suite(suite_path("refusal.yaml"))
    v4 = replay_suite(
        suite,
        RecordingClient.from_file(fixture_path("opus-4.responses.json"), model_version="opus-4"),
        run_id="r4",
    )
    v5 = replay_suite(
        suite,
        RecordingClient.from_file(fixture_path("opus-5.responses.json"), model_version="opus-5"),
        run_id="r5",
    )
    diffs = align_spans(v4, v5)
    dm = aggregate(diffs)
    md = render_markdown(dm, from_model="opus-4", to_model="opus-5", suite_name="refusal")
    assert "refusal-safety" in md
    assert "+50%" in md
    # tool-call column shows "—" (not applicable)
    assert "—" in md
