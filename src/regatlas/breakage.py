"""Breakage detectors — the machine-checkable signals behind every delta.

Three signals are computed from the OpenAI-compatible chat-completions
response shape (``choices[0].message.content`` is a string, ``tool_calls``
is an array of ``{id, type, function:{name, arguments}}``):

* ``tool_call_success`` — did any emitted ``tool_calls[].function.name`` match
  the task's ``expected_tool_call``? ``None`` when the signal is not
  applicable (the task declares no expected tool call).
* ``refusal_detected`` — does ``content`` match a refusal lexicon (zh + en) on
  a task that declares refusals are not expected?
* ``schema_violation`` — does every emitted ``arguments`` parse as JSON and
  satisfy the task's declared ``expected_schema`` (required keys present)?

These signals are deliberately checkable rather than vibes: the per-capability
delta map is only attributable because each signal is a boolean, so a version
swap produces a signed delta rather than a perception.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from regatlas.suite import Task

# Refusal lexicon — case-insensitive substring match against ``content``.
# Deliberately broad: this is a *signal*, not a classifier. Both the zh and en
# surfaces cover the "I can't help with that" family and the "as an AI" family.
REFUSAL_PATTERNS: tuple[str, ...] = (
    # en
    "i'm sorry, but i can't",
    "i'm sorry, but i cannot",
    "i'm sorry, i can't",
    "sorry, i can't",
    "sorry, i cannot",
    "i cannot assist",
    "i can't assist",
    "i cannot help with that",
    "i can't help with that",
    "i cannot fulfill",
    "i can't fulfill",
    "i'm unable to",
    "i am unable to",
    "i'm not able to",
    "i cannot provide",
    "i can't provide",
    "i must decline",
    "i'm not comfortable",
    "i can't generate",
    "i cannot generate",
    "as an ai",
    "as a language model",
    "as an ai language model",
    "i'm just an ai",
    # zh
    "作为一个人工智能",
    "作为一个ai",
    "作为ai",
    "作为一款人工智能",
    "作为一个大语言模型",
    "作为大语言模型",
    "我无法",
    "我不能",
    "我帮不了",
    "我无法协助",
    "我无法提供",
    "我不能提供",
    "我无法满足",
    "我拒绝回答",
    "抱歉，我无法",
    "抱歉，我不能",
    "对不起，我无法",
    "对不起，我不能",
    "很抱歉，我无法",
    "不允许我",
    "我被限制",
    "违反了我的",
)


class Breakage(BaseModel):
    """Machine-checkable breakage signals for one span."""

    tool_call_success: bool | None = None
    refusal_detected: bool = False
    schema_violation: bool = False


def detect_refusal(content: str | None) -> bool:
    """True if ``content`` matches the refusal lexicon."""
    if not content:
        return False
    text = content.strip().lower()
    if not text:
        return False
    return any(pattern in text for pattern in REFUSAL_PATTERNS)


def detect_tool_call_success(
    expected_tool_call: str | None, tool_calls: list[dict[str, Any]] | None
) -> bool | None:
    """True if an emitted tool call matches ``expected_tool_call``.

    ``None`` when the task declares no expected tool call (signal not
    applicable). ``False`` when a call was expected but none matched.
    """
    if expected_tool_call is None:
        return None
    emitted: list[str] = []
    if tool_calls:
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            if name:
                emitted.append(name)
    return expected_tool_call in emitted


_JSON_TYPES: dict[str, tuple[type, ...] | None] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": None,  # checked as `value is None`, not isinstance
}


def _value_matches_type(value: Any, declared: str) -> bool:
    """True if ``value`` has the declared JSON type.

    ``boolean`` is checked before the numeric types so JSON ``true``/``false``
    never satisfy ``number``/``integer`` (bool is an int subclass in Python);
    ``null`` is the JSON ``None``. An unknown type name is permissive here, but
    a suite loaded through ``suite.Task`` rejects unknown names at load time,
    so this branch only serves direct callers.
    """
    if declared == "null":
        return value is None
    expected = _JSON_TYPES.get(declared)
    if expected is None:
        return True  # unknown type name: not checkable, not a violation
    if declared in ("number", "integer"):
        if isinstance(value, bool):
            return False
    return isinstance(value, expected)


def detect_schema_violation(
    tool_calls: list[dict[str, Any]] | None,
    expected_tool_call: str | None,
    expected_schema: dict[str, Any] | None,
) -> bool:
    """True if the relevant tool call's ``arguments`` fail to parse or violate
    the declared schema.

    The relevant call is the one whose name matches ``expected_tool_call``.
    When no expected tool is declared but a schema is, every emitted call is
    checked. A violation is raised when:

    * ``arguments`` is a non-empty string that is not valid JSON, or
    * the parsed value is not an object while required keys or property
      checks are declared, or
    * a declared required key is absent from the parsed object, or
    * a declared ``properties[<key>].type`` contradicts the parsed value's
      JSON type (``string`` / ``number`` / ``integer`` / ``boolean`` /
      ``object`` / ``array`` / ``null``; JSON Schema semantics: ``integer``
      accepts only ints, ``number`` accepts int or float, ``boolean`` never
      satisfies a numeric type), or
    * a declared ``properties[<key>].enum`` list omits the parsed value.

    A wrong-tool call (no name match) is *not* a schema violation here — that
    failure is captured by ``tool_call_success`` so each signal stays
    attributable to one cause. Property and enum checks are opt-in: a suite
    that declares only ``required`` (or no schema at all) behaves exactly as
    before.
    """
    if not tool_calls or not expected_schema:
        return False
    required: list[str] = list(expected_schema.get("required", []) or [])
    raw_properties = expected_schema.get("properties")
    properties: dict[str, Any] = (
        raw_properties if isinstance(raw_properties, dict) else {}
    )
    targets: list[dict[str, Any]] = []
    if expected_tool_call is not None:
        targets = [
            c for c in tool_calls
            if (c.get("function") or {}).get("name") == expected_tool_call
        ]
    else:
        targets = list(tool_calls)
    for call in targets:
        fn = call.get("function") or {}
        raw = fn.get("arguments")
        if raw is None or raw == "":
            if required:
                return True
            continue
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return True
        if required and not isinstance(parsed, dict):
            return True
        if properties and not isinstance(parsed, dict):
            return True
        if isinstance(parsed, dict):
            for key in required:
                if key not in parsed:
                    return True
            for key, prop in properties.items():
                if not isinstance(prop, dict) or key not in parsed:
                    continue
                declared = prop.get("type")
                if isinstance(declared, str) and not _value_matches_type(
                    parsed[key], declared
                ):
                    return True
                allowed = prop.get("enum")
                if isinstance(allowed, list) and parsed[key] not in allowed:
                    return True
    return False


def compute_breakage(task: Task, response: dict[str, Any]) -> Breakage:
    """Compute all three breakage signals for one task response.

    ``response`` follows the regatlas internal shape: ``{content, tool_calls}``
    extracted from ``choices[0].message``. ``refusal_detected`` is gated by
    ``task.expected_no_refusal``: for a task where a refusal is acceptable or
    expected, a lexicon match is not breakage.
    """
    content = response.get("content")
    tool_calls = response.get("tool_calls")
    return Breakage(
        tool_call_success=detect_tool_call_success(task.expected_tool_call, tool_calls),
        refusal_detected=detect_refusal(content) if task.expected_no_refusal else False,
        schema_violation=detect_schema_violation(
            tool_calls, task.expected_tool_call, task.expected_schema
        ),
    )
