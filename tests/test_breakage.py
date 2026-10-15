"""Unit tests for the breakage detectors (milestone m1)."""
from __future__ import annotations

from regatlas.breakage import (
    Breakage,
    compute_breakage,
    detect_refusal,
    detect_schema_violation,
    detect_tool_call_success,
)
from regatlas.suite import Task


def _task(**kw) -> Task:
    base = dict(id="x", capability="c", prompt="p")
    base.update(kw)
    return Task(**base)


# --- refusal detection ---------------------------------------------------

def test_refusal_none_content_is_not_refusal() -> None:
    assert detect_refusal(None) is False
    assert detect_refusal("") is False
    assert detect_refusal("   ") is False


def test_refusal_english_lexicon() -> None:
    assert detect_refusal("I'm sorry, but I can't help with that.") is True
    assert detect_refusal("As an AI language model, I cannot do that.") is True
    assert detect_refusal("I'm unable to provide that information.") is True


def test_refusal_chinese_lexicon() -> None:
    assert detect_refusal("作为一个人工智能，我无法协助你完成这件事。") is True
    assert detect_refusal("抱歉，我无法回答这个问题。") is True
    assert detect_refusal("对不起，我不能帮你做这件事。") is True


def test_refusal_helpful_answer_is_not_refusal() -> None:
    helpful = "Three tips to speed up your Python for-loop: hoist invariants, use locals, prefer comprehensions."
    assert detect_refusal(helpful) is False


# --- tool call success ---------------------------------------------------

def test_tool_call_success_match() -> None:
    calls = [{"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]
    assert detect_tool_call_success("get_weather", calls) is True


def test_tool_call_success_wrong_tool() -> None:
    calls = [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}]
    assert detect_tool_call_success("get_weather", calls) is False


def test_tool_call_success_none_when_no_calls_expected_none() -> None:
    assert detect_tool_call_success(None, None) is None


def test_tool_call_success_expected_but_no_calls_is_false() -> None:
    assert detect_tool_call_success("get_weather", None) is False


# --- schema violation ---------------------------------------------------

def test_schema_violation_valid_json_with_required_keys() -> None:
    calls = [{"function": {"name": "get_weather", "arguments": '{"location":"Beijing"}'}}]
    assert detect_schema_violation(calls, "get_weather", {"required": ["location"]}) is False


def test_schema_violation_malformed_json() -> None:
    calls = [{"function": {"name": "calculate", "arguments": "not json{{"}}]
    assert detect_schema_violation(calls, "calculate", {"required": ["expression"]}) is True


def test_schema_violation_missing_required_key() -> None:
    calls = [{"function": {"name": "send_email", "arguments": '{"to":"a@b.com"}'}}]
    assert detect_schema_violation(calls, "send_email", {"required": ["to", "subject"]}) is True


def test_schema_violation_wrong_tool_not_counted_as_schema() -> None:
    # wrong tool call should not trigger schema_violation (captured by tool_call_success)
    calls = [{"function": {"name": "web_search", "arguments": '{"query":"x"}'}}]
    assert detect_schema_violation(calls, "get_weather", {"required": ["location"]}) is False


def test_schema_violation_no_schema_declared_is_false() -> None:
    calls = [{"function": {"name": "x", "arguments": "not json"}}]
    assert detect_schema_violation(calls, "x", None) is False


# --- richer validation semantics: properties type checks + enum -----------

def _call(args: str) -> list[dict]:
    return [{"function": {"name": "get_weather", "arguments": args}}]


def test_schema_properties_type_match_is_not_violation() -> None:
    schema = {"properties": {"location": {"type": "string"}}}
    assert detect_schema_violation(_call('{"location":"Beijing"}'), "get_weather", schema) is False


def test_schema_properties_type_mismatch_is_violation() -> None:
    schema = {"properties": {"location": {"type": "string"}}}
    assert detect_schema_violation(_call('{"location":123}'), "get_weather", schema) is True


def test_schema_integer_rejects_float_and_number_accepts_int() -> None:
    schema_int = {"properties": {"count": {"type": "integer"}}}
    assert detect_schema_violation(_call('{"count":1.5}'), "get_weather", schema_int) is True
    assert detect_schema_violation(_call('{"count":2}'), "get_weather", schema_int) is False
    schema_num = {"properties": {"ratio": {"type": "number"}}}
    assert detect_schema_violation(_call('{"ratio":2}'), "get_weather", schema_num) is False


def test_schema_boolean_never_satisfies_numeric_type() -> None:
    schema = {"properties": {"count": {"type": "number"}}}
    assert detect_schema_violation(_call('{"count":true}'), "get_weather", schema) is True


def test_schema_object_array_null_types() -> None:
    schema = {"properties": {"opts": {"type": "object"}, "tags": {"type": "array"}}}
    ok = '{"opts":{"a":1},"tags":["x"]}'
    assert detect_schema_violation(_call(ok), "get_weather", schema) is False
    assert detect_schema_violation(_call('{"opts":null,"tags":"x"}'), "get_weather", schema) is True
    schema_null = {"properties": {"opts": {"type": "null"}}}
    assert detect_schema_violation(_call('{"opts":null}'), "get_weather", schema_null) is False


def test_schema_enum_hit_and_miss() -> None:
    schema = {"properties": {"unit": {"type": "string", "enum": ["c", "f"]}}}
    assert detect_schema_violation(_call('{"unit":"c"}'), "get_weather", schema) is False
    assert detect_schema_violation(_call('{"unit":"k"}'), "get_weather", schema) is True


def test_schema_properties_undeclared_keys_and_missing_keys_ignored() -> None:
    """Extra keys are allowed and absent keys stay a `required` concern."""
    schema = {"properties": {"location": {"type": "string"}}}
    assert detect_schema_violation(_call('{"other":true}'), "get_weather", schema) is False
    assert detect_schema_violation(_call("{}"), "get_weather", schema) is False


def test_schema_required_only_behavior_unchanged() -> None:
    """Backward compatibility: required-only suites behave exactly as before."""
    schema = {"required": ["location"]}
    assert detect_schema_violation(_call('{"location":123}'), "get_weather", schema) is False
    assert detect_schema_violation(_call("{}"), "get_weather", schema) is True


def test_schema_properties_non_object_arguments_is_violation() -> None:
    schema = {"properties": {"location": {"type": "string"}}}
    assert detect_schema_violation(_call('"just a string"'), "get_weather", schema) is True


def test_schema_type_mismatch_flows_through_pipeline() -> None:
    """A type-mismatched argument becomes a +1 schema delta through align."""
    from regatlas.align import align_spans
    from regatlas.trajectory import Response, Span

    suite_task = _task(
        expected_tool_call="get_weather",
        expected_schema={"properties": {"location": {"type": "string"}}},
    )
    good_resp = {"content": None, "tool_calls": _call('{"location":"Beijing"}')}
    bad_resp = {"content": None, "tool_calls": _call('{"location":123}')}
    good_br = compute_breakage(suite_task, good_resp)
    bad_br = compute_breakage(suite_task, bad_resp)
    assert good_br.schema_violation is False
    assert bad_br.schema_violation is True

    def _span(br, model):
        return Span(
            run_id="r", model_version=model, task_id="x", turn_idx=0,
            capability="tool-calling", request={}, response=Response(),
            breakage=br,
        )

    diffs = align_spans([_span(good_br, "a")], [_span(bad_br, "b")])
    assert diffs[0].deltas["schema_violation"] == 1


# --- compute_breakage integration ----------------------------------------

def test_compute_breakage_correct_tool_call() -> None:
    task = _task(expected_tool_call="get_weather", expected_schema={"required": ["location"]})
    resp = {"content": None, "tool_calls": [{"function": {"name": "get_weather", "arguments": '{"location":"Beijing"}'}}]}
    br = compute_breakage(task, resp)
    assert br == Breakage(tool_call_success=True, refusal_detected=False, schema_violation=False)


def test_compute_breakage_refusal_task() -> None:
    task = _task()
    resp = {"content": "I'm sorry, but I can't help with that.", "tool_calls": None}
    br = compute_breakage(task, resp)
    assert br.refusal_detected is True
    assert br.tool_call_success is None
    assert br.schema_violation is False
