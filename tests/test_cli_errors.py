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

from conftest import FIXTURES, fixture_path, suite_path

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


def _write_diff_doc(tmp_path: Path, name: str, span_diffs_json: str) -> Path:
    doc = tmp_path / name
    doc.write_text(
        '{"from_model": "a", "to_model": "b", "suite": "s",'
        f' "span_diffs": {span_diffs_json}}}',
        encoding="utf-8",
    )
    return doc


def test_report_span_diffs_null_crashes_no_more(tmp_path: Path) -> None:
    """v0.2.0 raised TypeError ('NoneType' object is not iterable) at cli.py:88."""
    doc = _write_diff_doc(tmp_path, "null-spans.json", "null")
    result = runner.invoke(app, ["report", "--diff", str(doc)])
    assert result.exit_code == 2
    _assert_err(result, "span_diffs", "list")


def test_report_span_diffs_non_list_rejected(tmp_path: Path) -> None:
    doc = _write_diff_doc(tmp_path, "int-spans.json", "5")
    result = runner.invoke(app, ["report", "--diff", str(doc)])
    assert result.exit_code == 2
    _assert_err(result, "span_diffs", "list")


def test_export_span_diffs_null_crashes_no_more(tmp_path: Path) -> None:
    """export shares _load_diff_doc, so the null case crashed identically."""
    doc = _write_diff_doc(tmp_path, "null-spans.json", "null")
    result = runner.invoke(
        app, ["export", "--diff", str(doc), "--format", "json"]
    )
    assert result.exit_code == 2
    _assert_err(result, "span_diffs", "list")


def test_report_missing_span_diffs_key_still_empty_atlas(tmp_path: Path) -> None:
    """A MISSING span_diffs key stays an intentional empty atlas (exit 0)."""
    doc = tmp_path / "no-key.json"
    doc.write_text('{"from_model": "a", "to_model": "b", "suite": "s"}', encoding="utf-8")
    result = runner.invoke(app, ["report", "--diff", str(doc)])
    assert result.exit_code == 0
    assert "regatlas delta map" in result.stdout


def test_replay_out_unwritable_path(tmp_path: Path) -> None:
    """v0.2.0 leaked a FileNotFoundError traceback from write_trajectory."""
    result = _replay_toolcalling(
        fixture_path("opus-4.responses.json"), tmp_path / "nope" / "t.jsonl"
    )
    assert result.exit_code == 2
    _assert_err(result, "t.jsonl")


def test_diff_out_unwritable_path(tmp_path: Path) -> None:
    good = tmp_path / "traj.jsonl"
    ok = _replay_toolcalling(fixture_path("opus-4.responses.json"), good)
    assert ok.exit_code == 0, _stderr_compact(ok)
    result = runner.invoke(
        app,
        ["diff", "--from", str(good), "--to", str(good),
         "--out", str(tmp_path / "nope" / "d.json")],
    )
    assert result.exit_code == 2
    _assert_err(result, "d.json")


def test_report_out_unwritable_path(tmp_path: Path) -> None:
    doc = _write_diff_doc(
        tmp_path, "ok.json",
        '[{"task_id": "t1", "turn_idx": 0, "capability": "c",'
        ' "from_breakage": {}, "to_breakage": {}, "deltas": {}}]',
    )
    result = runner.invoke(
        app, ["report", "--diff", str(doc), "--out", str(tmp_path / "nope" / "m.md")]
    )
    assert result.exit_code == 2
    _assert_err(result, "m.md")


def test_export_out_unwritable_path(tmp_path: Path) -> None:
    doc = _write_diff_doc(tmp_path, "ok.json", "[]")
    result = runner.invoke(
        app,
        ["export", "--diff", str(doc), "--format", "json",
         "--out", str(tmp_path / "nope" / "x.json")],
    )
    assert result.exit_code == 2
    _assert_err(result, "x.json")


def test_run_out_dir_blocked_by_file(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "run",
            "--suite", str(suite_path("toolcalling.yaml")),
            "--models", "opus-4",
            "--recordings", str(FIXTURES),
            "--out-dir", str(blocker / "sub"),
        ],
    )
    assert result.exit_code == 2
    _assert_err(result, "blocker")


def test_out_writable_path_still_writes(tmp_path: Path) -> None:
    """Regression: writable destinations produce the identical artifact."""
    doc = _write_diff_doc(tmp_path, "ok.json", "[]")
    out = tmp_path / "m.md"
    result = runner.invoke(app, ["report", "--diff", str(doc), "--out", str(out)])
    assert result.exit_code == 0, _stderr_compact(result)
    stdout_only = runner.invoke(app, ["report", "--diff", str(doc)])
    assert out.read_text(encoding="utf-8") == stdout_only.stdout


def test_diff_duplicate_span_keys_exit_2(tmp_path: Path) -> None:
    """v0.2.0 silently aligned last-wins on a concatenated-run trajectory."""
    good = tmp_path / "traj_to.jsonl"
    ok = _replay_toolcalling(fixture_path("opus-4.responses.json"), good)
    assert ok.exit_code == 0, _stderr_compact(ok)

    line = good.read_text(encoding="utf-8").splitlines()[0]
    dup = tmp_path / "traj_dup.jsonl"
    dup.write_text(line + "\n" + line + "\n", encoding="utf-8")

    result = runner.invoke(
        app, ["diff", "--from", str(dup), "--to", str(good)]
    )
    assert result.exit_code == 2
    _assert_err(result, "duplicate", "t1")
