"""CLI error contract — bad inputs exit 2 with a clean message, never a traceback.

Each case reproduces a crash observed on v0.1.0 (raw traceback + exit 1) and
pins the fixed contract: a one-line ``error:`` naming the offending input and
exit code 2, matching the CLI's existing unconfigured-endpoint error contract.
"""
from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from regatlas.cli import app

from conftest import fixture_path, suite_path

runner = CliRunner()


def _stderr_compact(result) -> str:
    """Stderr with all whitespace removed.

    The rich console wraps error lines at the terminal width (80 on CI
    runners) and can break inside a path or phrase, so assertions match
    against whitespace-free text.
    """
    try:
        text = result.stderr
    except ValueError:  # stderr merged into stdout on older click
        text = result.output
    return re.sub(r"\s+", "", text)


def _assert_err(result, *needles: str) -> None:
    """Assert the error contract: exit 2, an error: line, no traceback."""
    compact = _stderr_compact(result)
    assert "error:" in compact
    assert "Traceback" not in compact
    for needle in needles:
        assert re.sub(r"\s+", "", needle) in compact, needle


def _replay_toolcalling(recording: Path, out: Path):
    return runner.invoke(
        app,
        [
            "replay",
            "--suite", str(suite_path("toolcalling.yaml")),
            "--model", "opus-4",
            "--recording", str(recording),
            "--out", str(out),
        ],
    )


def test_replay_missing_recording_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.responses.json"
    result = _replay_toolcalling(missing, tmp_path / "t.jsonl")
    assert result.exit_code == 2
    _assert_err(result, "nope.responses.json")


def test_replay_recording_not_an_object(tmp_path: Path) -> None:
    rec = tmp_path / "array.responses.json"
    rec.write_text('[{"a": 1}]', encoding="utf-8")
    result = _replay_toolcalling(rec, tmp_path / "t.jsonl")
    assert result.exit_code == 2
    _assert_err(result, "recording")


def test_replay_malformed_suite_yaml(tmp_path: Path) -> None:
    suite = tmp_path / "broken.yaml"
    suite.write_text(
        "name: broken\ntasks:\n  - id: t1\n    prompt: hi\n", encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "replay",
            "--suite", str(suite),
            "--model", "opus-4",
            "--recording", str(fixture_path("opus-4.responses.json")),
            "--out", str(tmp_path / "t.jsonl"),
        ],
    )
    assert result.exit_code == 2
    _assert_err(result, "broken.yaml")


def test_run_missing_recordings_dir(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--suite", str(suite_path("toolcalling.yaml")),
            "--models", "opus-4",
            "--recordings", str(tmp_path / "missing"),
        ],
    )
    assert result.exit_code == 2
    _assert_err(result, "opus-4.responses.json")


def test_diff_malformed_trajectory_line(tmp_path: Path) -> None:
    good = tmp_path / "traj_good.jsonl"
    ok = _replay_toolcalling(fixture_path("opus-4.responses.json"), good)
    assert ok.exit_code == 0, _stderr_compact(ok)

    bad = tmp_path / "traj_bad.jsonl"
    bad.write_text('{"bad": "line"}\n', encoding="utf-8")
    result = runner.invoke(
        app,
        ["diff", "--from", str(bad), "--to", str(good)],
    )
    assert result.exit_code == 2
    _assert_err(result, "traj_bad.jsonl")


def test_report_missing_diff_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["report", "--diff", str(tmp_path / "nope-diff.json")]
    )
    assert result.exit_code == 2
    _assert_err(result, "nope-diff.json")


def test_report_span_diffs_fail_validation(tmp_path: Path) -> None:
    doc = tmp_path / "invalid-span-diff.json"
    doc.write_text(
        '{"from_model": "a", "to_model": "b", "suite": "s",'
        ' "span_diffs": [{"task_id": "t1"}]}',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["report", "--diff", str(doc)])
    assert result.exit_code == 2
    _assert_err(result, "invalid-span-diff.json")


def test_report_non_object_diff_doc(tmp_path: Path) -> None:
    doc = tmp_path / "list-doc.json"
    doc.write_text("[]", encoding="utf-8")
    result = runner.invoke(app, ["report", "--diff", str(doc)])
    assert result.exit_code == 2
    _assert_err(result, "must be a JSON object")


def test_report_missing_delta_keys_renders_as_not_applicable(tmp_path: Path) -> None:
    """v0.1.0 crashed with KeyError on a schema-valid doc with empty deltas."""
    doc = tmp_path / "empty-deltas.json"
    doc.write_text(
        '{"from_model": "a", "to_model": "b", "suite": "s",'
        ' "span_diffs": [{"task_id": "t1", "turn_idx": 0, "capability": "c",'
        ' "from_breakage": {"refusal_detected": false, "schema_violation": false},'
        ' "to_breakage": {"refusal_detected": false, "schema_violation": false},'
        ' "deltas": {}}]}',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["report", "--diff", str(doc)])
    assert result.exit_code == 0
    assert "KeyError" not in _stderr_compact(result)
    assert "| c |" in result.stdout  # the row renders with em-dashes for N/A signals
