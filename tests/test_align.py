"""Tests for span alignment and signed deltas (milestone m2)."""
from __future__ import annotations

from regatlas.align import align_spans, signed_delta
from regatlas.breakage import Breakage
from regatlas.replay import RecordingClient, replay_suite
from regatlas.suite import load_suite
from regatlas.trajectory import Span, Response

from conftest import fixture_path, suite_path


def test_signed_delta_polarity() -> None:
    # tool_call_success: True=1 good; True->False = -1 (regression)
    assert signed_delta(False, True) == -1
    # False->True = +1 (improvement)
    assert signed_delta(True, False) == 1
    assert signed_delta(True, True) == 0
    assert signed_delta(False, False) == 0
    # None when not applicable on either side
    assert signed_delta(None, True) is None
    assert signed_delta(False, None) is None


def _span(task_id: str, capability: str, br: Breakage, model: str = "m") -> Span:
    return Span(
        run_id="r",
        model_version=model,
        task_id=task_id,
        turn_idx=0,
        capability=capability,
        request={},
        response=Response(),
        breakage=br,
    )


def test_align_pairs_by_task_id_and_turn() -> None:
    from_spans = [
        _span("t1", "tool-calling", Breakage(tool_call_success=True), model="opus-4"),
        _span("t2", "tool-calling", Breakage(tool_call_success=True), model="opus-4"),
    ]
    to_spans = [
        _span("t1", "tool-calling", Breakage(tool_call_success=False), model="opus-5"),
        _span("t3", "tool-calling", Breakage(tool_call_success=True), model="opus-5"),
    ]
    diffs = align_spans(from_spans, to_spans)
    by_task = {d.task_id: d for d in diffs}
    assert set(by_task) == {"t1", "t2", "t3"}
    # t1: True -> False = -1 (regression)
    assert by_task["t1"].deltas["tool_call_success"] == -1
    # t2 only on from side: to_breakage defaults to None -> delta not applicable
    assert by_task["t2"].deltas["tool_call_success"] is None
    # t3 only on to side: from_breakage defaults to None -> delta not applicable
    assert by_task["t3"].deltas["tool_call_success"] is None
    assert by_task["t1"].from_model == "opus-4"
    assert by_task["t1"].to_model == "opus-5"


def test_align_refusal_delta_polarity() -> None:
    from_spans = [_span("r1", "refusal-safety", Breakage(refusal_detected=False), model="opus-4")]
    to_spans = [_span("r1", "refusal-safety", Breakage(refusal_detected=True), model="opus-5")]
    diffs = align_spans(from_spans, to_spans)
    # False -> True = +1 (regression, refusal rose)
    assert diffs[0].deltas["refusal_detected"] == 1
    assert diffs[0].deltas["schema_violation"] == 0


def test_align_on_bundled_toolcalling_fixture() -> None:
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
    assert len(diffs) == len(suite.tasks)
    by_task = {d.task_id: d for d in diffs}
    # t1: wrong tool (web_search instead of get_weather) -> success True->False = -1
    assert by_task["t1"].deltas["tool_call_success"] == -1
    # t3: schema violation introduced -> schema False->True = +1, success stays True (name matches)
    assert by_task["t3"].deltas["schema_violation"] == 1
    assert by_task["t3"].deltas["tool_call_success"] == 0
    # t5: no tool call emitted -> success True->False = -1
    assert by_task["t5"].deltas["tool_call_success"] == -1
    # t2/t4/t6: unchanged
    for stable in ("t2", "t4", "t6"):
        assert by_task[stable].deltas["tool_call_success"] == 0
        assert by_task[stable].deltas["schema_violation"] == 0
