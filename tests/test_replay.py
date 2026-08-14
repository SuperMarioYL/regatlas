"""Tests for the replay engine and trajectory IO (milestone m1)."""
from __future__ import annotations

import json

from regatlas.replay import (
    RecordingClient,
    env_name,
    list_endpoints,
    replay_suite,
    resolve_endpoint,
)
from regatlas.suite import Suite, Task
from regatlas.trajectory import read_trajectory, write_trajectory

from conftest import fixture_path, suite_path


def test_env_name_normalizes_alias() -> None:
    assert env_name("opus-4") == "OPUS4"
    assert env_name("glm-4.6") == "GLM46"
    assert env_name("deepseek-v3") == "DEEPSEEKV3"


def test_list_endpoints_includes_known_models() -> None:
    names = [ep.name for ep in list_endpoints()]
    assert "opus-4" in names
    assert "qwen-3" in names


def test_resolve_endpoint_unconfigured_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("REGATLAS_OPUS4_BASE_URL", raising=False)
    monkeypatch.delenv("REGATLAS_OPUS4_API_KEY", raising=False)
    ep = resolve_endpoint("opus-4")
    assert ep.name == "opus-4"
    assert ep.configured is False
    assert ep.base_url is None


def test_resolve_endpoint_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("REGATLAS_OPUS4_BASE_URL", "https://example.test")
    monkeypatch.setenv("REGATLAS_OPUS4_API_KEY", "sk-test")
    monkeypatch.setenv("REGATLAS_OPUS4_MODEL", "opus-4-2026")
    ep = resolve_endpoint("opus-4")
    assert ep.base_url == "https://example.test"
    assert ep.api_key == "sk-test"
    assert ep.model == "opus-4-2026"
    assert ep.configured is True


def _suite() -> Suite:
    return Suite(
        name="mini",
        tasks=[
            Task(
                id="t1",
                capability="tool-calling",
                prompt="weather?",
                expected_tool_call="get_weather",
                expected_schema={"required": ["location"]},
            ),
            Task(
                id="r1",
                capability="refusal-safety",
                prompt="help?",
                expected_no_refusal=True,
            ),
        ],
    )


def test_recording_client_returns_canned_response() -> None:
    responses = {
        "t1": {"content": None, "tool_calls": [{"function": {"name": "get_weather", "arguments": '{"location":"Beijing"}'}}]},
        "r1": {"content": "Sure, here is the help.", "tool_calls": None},
    }
    client = RecordingClient(responses, model_version="opus-4")
    t1 = _suite().tasks[0]
    out = client.complete(t1)
    assert out["tool_calls"][0]["function"]["name"] == "get_weather"


def test_recording_client_missing_task_raises() -> None:
    client = RecordingClient({}, model_version="opus-4")
    try:
        client.complete(_suite().tasks[0])
    except KeyError:
        return
    raise AssertionError("expected KeyError for missing task")


def test_replay_suite_produces_capability_tagged_spans() -> None:
    responses = {
        "t1": {"content": None, "tool_calls": [{"function": {"name": "get_weather", "arguments": '{"location":"Beijing"}'}}]},
        "r1": {"content": "I'm sorry, but I can't help with that.", "tool_calls": None},
    }
    client = RecordingClient(responses, model_version="opus-4")
    spans = replay_suite(_suite(), client, run_id="run-1")
    assert len(spans) == 2
    by_task = {s.task_id: s for s in spans}
    assert by_task["t1"].capability == "tool-calling"
    assert by_task["t1"].breakage.tool_call_success is True
    assert by_task["t1"].breakage.schema_violation is False
    assert by_task["r1"].capability == "refusal-safety"
    assert by_task["r1"].breakage.refusal_detected is True
    assert by_task["r1"].breakage.tool_call_success is None
    for span in spans:
        assert span.run_id == "run-1"
        assert span.model_version == "opus-4"


def test_trajectory_round_trip(tmp_path) -> None:
    responses = {
        "t1": {"content": None, "tool_calls": [{"function": {"name": "get_weather", "arguments": '{"location":"Beijing"}'}}]},
        "r1": {"content": "ok", "tool_calls": None},
    }
    client = RecordingClient(responses, model_version="opus-4")
    spans = replay_suite(_suite(), client, run_id="run-rt")
    out = tmp_path / "traj.jsonl"
    write_trajectory(out, spans)
    loaded = read_trajectory(out)
    assert len(loaded) == 2
    assert loaded[0].task_id == "t1"
    assert loaded[0].response.tool_calls[0]["function"]["name"] == "get_weather"
    assert loaded[1].task_id == "r1"
    # JSONL: one JSON object per line
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "breakage" in obj
        assert "capability" in obj


def test_replay_suite_on_bundled_toolcalling_fixture() -> None:
    """End-to-end on the shipped toolcalling suite + opus-4 recording."""
    from regatlas.suite import load_suite

    suite = load_suite(suite_path("toolcalling.yaml"))
    client = RecordingClient.from_file(fixture_path("opus-4.responses.json"), model_version="opus-4")
    spans = replay_suite(suite, client, run_id="run-bundled")
    assert len(spans) == len(suite.tasks)
    # opus-4 baseline: every tool-calling task succeeds with valid schema, no refusal
    for span in spans:
        assert span.breakage.refusal_detected is False
        assert span.breakage.schema_violation is False
        assert span.breakage.tool_call_success is True
