"""End-to-end CLI integration test — offline pipeline across all milestones."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from regatlas.cli import app
from regatlas import __version__

from conftest import FIXTURES, fixture_path, suite_path

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_list_models() -> None:
    result = runner.invoke(app, ["--list-models"])
    assert result.exit_code == 0
    assert "opus-4" in result.stdout
    assert "qwen-3" in result.stdout


def test_full_pipeline_toolcalling(tmp_path: Path) -> None:
    traj_v4 = tmp_path / "traj_opus-4.jsonl"
    traj_v5 = tmp_path / "traj_opus-5.jsonl"
    diff_doc = tmp_path / "diff.json"

    # m1: replay both model versions offline
    r1 = runner.invoke(
        app,
        [
            "replay",
            "--suite", str(suite_path("toolcalling.yaml")),
            "--model", "opus-4",
            "--recording", str(fixture_path("opus-4.responses.json")),
            "--out", str(traj_v4),
        ],
    )
    assert r1.exit_code == 0, r1.stderr
    assert traj_v4.exists()
    first_span = json.loads(traj_v4.read_text().splitlines()[0])
    assert first_span["breakage"]["tool_call_success"] is True

    r2 = runner.invoke(
        app,
        [
            "replay",
            "--suite", str(suite_path("toolcalling.yaml")),
            "--model", "opus-5",
            "--recording", str(fixture_path("opus-5.responses.json")),
            "--out", str(traj_v5),
        ],
    )
    assert r2.exit_code == 0, r2.stderr
    assert traj_v5.exists()

    # m2: diff aligns spans and emits signed deltas
    r3 = runner.invoke(
        app,
        [
            "diff",
            "--from", str(traj_v4),
            "--to", str(traj_v5),
            "--out", str(diff_doc),
        ],
    )
    assert r3.exit_code == 0, r3.stderr
    doc = json.loads(diff_doc.read_text())
    assert doc["from_model"] == "opus-4"
    assert doc["to_model"] == "opus-5"
    assert len(doc["span_diffs"]) == 6
    deltas_by_task = {d["task_id"]: d["deltas"] for d in doc["span_diffs"]}
    assert deltas_by_task["t1"]["tool_call_success"] == -1
    assert deltas_by_task["t3"]["schema_violation"] == 1

    # m3: report renders the per-capability markdown delta map
    r4 = runner.invoke(app, ["report", "--diff", str(diff_doc)])
    assert r4.exit_code == 0, r4.stderr
    out = r4.stdout
    assert "tool-calling" in out
    assert "-33%" in out
    assert "+17%" in out
    assert "```json" in out


def test_diff_baseline_candidate_aliases_and_report_refusal(tmp_path: Path) -> None:
    """run + diff --baseline/--candidate (alias flags) on the refusal suite."""
    out_dir = tmp_path
    r = runner.invoke(
        app,
        [
            "run",
            "--suite", str(suite_path("refusal.yaml")),
            "--models", "opus-4,opus-5",
            "--recordings", str(FIXTURES),
            "--out-dir", str(out_dir),
        ],
    )
    assert r.exit_code == 0, r.stderr
    assert (out_dir / "traj_opus-4.jsonl").exists()
    assert (out_dir / "traj_opus-5.jsonl").exists()

    diff_doc = out_dir / "diff.json"
    cwd = Path.cwd()
    try:
        import os

        os.chdir(out_dir)
        # alias flags + bare model aliases resolving to traj_<alias>.jsonl
        r2 = runner.invoke(
            app,
            ["diff", "--baseline", "opus-4", "--candidate", "opus-5", "--out", "diff.json"],
        )
        assert r2.exit_code == 0, r2.stderr
    finally:
        os.chdir(cwd)

    doc = json.loads(diff_doc.read_text())
    assert len(doc["span_diffs"]) == 4

    r3 = runner.invoke(app, ["report", "--diff", str(diff_doc)])
    assert r3.exit_code == 0, r3.stderr
    assert "refusal-safety" in r3.stdout
    assert "+50%" in r3.stdout
