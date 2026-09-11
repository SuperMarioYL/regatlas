"""Export adapters — diff documents land in existing trace stores (v0.2 roadmap)."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from regatlas.cli import app

from conftest import FIXTURES, suite_path

runner = CliRunner()


def _build_diff(tmp_path: Path) -> Path:
    """Run the offline pipeline up to a diff.json document."""
    r = runner.invoke(
        app,
        [
            "run",
            "--suite", str(suite_path("toolcalling.yaml")),
            "--models", "opus-4,opus-5",
            "--recordings", str(FIXTURES),
            "--out-dir", str(tmp_path),
        ],
    )
    assert r.exit_code == 0, r.stderr
    diff_doc = tmp_path / "diff.json"
    r2 = runner.invoke(
        app,
        [
            "diff",
            "--from", str(tmp_path / "traj_opus-4.jsonl"),
            "--to", str(tmp_path / "traj_opus-5.jsonl"),
            "--out", str(diff_doc),
        ],
    )
    assert r2.exit_code == 0, r2.stderr
    return diff_doc


def test_export_langsmith_runs(tmp_path: Path) -> None:
    diff_doc = _build_diff(tmp_path)
    result = runner.invoke(
        app, ["export", "--diff", str(diff_doc), "--format", "langsmith"]
    )
    assert result.exit_code == 0, result.stderr
    runs = [json.loads(line) for line in result.stdout.splitlines() if line]
    assert len(runs) == 6
    ids = set()
    for run in runs:
        assert run["run_type"] == "chain"
        assert run["name"].startswith("regatlas:diff:t")
        assert run["inputs"]["capability"] == "tool-calling"
        ids.add(run["id"])
    assert len(ids) == 6  # deterministic, unique per span

    # feedback scores mirror the diff document's signed deltas exactly
    doc = json.loads(diff_doc.read_text(encoding="utf-8"))
    deltas_by_task = {d["task_id"]: d["deltas"] for d in doc["span_diffs"]}
    feedback = {
        run["name"].rsplit(":", 1)[1]: {f["key"]: f["score"] for f in run["feedback"]}
        for run in runs
    }
    for task_id, deltas in deltas_by_task.items():
        for key, value in deltas.items():
            assert feedback[task_id][f"regatlas.{key}_delta"] == value


def test_export_langfuse_ingestion_batch(tmp_path: Path) -> None:
    diff_doc = _build_diff(tmp_path)
    result = runner.invoke(
        app, ["export", "--diff", str(diff_doc), "--format", "langfuse"]
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    batch = doc["batch"]
    traces = [e for e in batch if e["type"] == "trace-create"]
    observations = [e for e in batch if e["type"] == "observation-create"]
    scores = [e for e in batch if e["type"] == "score-create"]
    # one capability in the toolcalling suite -> one atlas trace, 6 spans
    assert len(traces) == 1
    assert traces[0]["body"]["name"] == "regatlas:atlas:tool-calling"
    assert len(observations) == 6
    trace_id = traces[0]["body"]["id"]
    assert all(o["body"]["traceId"] == trace_id for o in observations)
    assert all(o["body"]["type"] == "SPAN" for o in observations)
    # one score per non-null delta, attached to the capability trace
    doc_deltas = json.loads(diff_doc.read_text(encoding="utf-8"))["span_diffs"]
    expected_scores = sum(
        1 for d in doc_deltas for v in d["deltas"].values() if v is not None
    )
    assert len(scores) == expected_scores
    assert all(s["body"]["traceId"] == trace_id for s in scores)
    assert all(s["body"]["name"].startswith("regatlas.") for s in scores)


def test_export_json_matches_report_block(tmp_path: Path) -> None:
    diff_doc = _build_diff(tmp_path)
    result = runner.invoke(
        app, ["export", "--diff", str(diff_doc), "--format", "json"]
    )
    assert result.exit_code == 0, result.stderr
    exported = json.loads(result.stdout)

    report = runner.invoke(app, ["report", "--diff", str(diff_doc)])
    assert report.exit_code == 0, report.stderr
    embedded = json.loads(
        report.stdout.split("```json")[1].split("```")[0]
    )
    assert exported == embedded
    assert exported["tool-calling"]["n_tasks"] == 6


def test_export_writes_out_file(tmp_path: Path) -> None:
    diff_doc = _build_diff(tmp_path)
    dest = tmp_path / "atlas.json"
    result = runner.invoke(
        app,
        [
            "export", "--diff", str(diff_doc),
            "--format", "json", "--out", str(dest),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(dest.read_text(encoding="utf-8"))["tool-calling"]["n_tasks"] == 6


def test_export_unknown_format_exits_2(tmp_path: Path) -> None:
    diff_doc = _build_diff(tmp_path)
    result = runner.invoke(
        app, ["export", "--diff", str(diff_doc), "--format", "csv"]
    )
    assert result.exit_code == 2
    assert "csv" in result.output
    assert "langsmith" in result.output


def test_export_missing_diff_file_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["export", "--diff", str(tmp_path / "nope.json"), "--format", "json"]
    )
    assert result.exit_code == 2
    assert "error:" in result.output
