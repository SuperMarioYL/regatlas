"""Suite model — user-declared task-suite loaded from YAML.

A Suite is a named list of Tasks. Each Task declares the capability it
exercises, the prompt sent to the model, the tools exposed, and the
machine-checkable expectations (`expected_tool_call`, `expected_no_refusal`,
`expected_schema`) that the breakage detectors evaluate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

# JSON type names accepted in ``expected_schema.properties.<key>.type``. The
# detector's ``_JSON_TYPES`` map must cover exactly this vocabulary; a test in
# tests/test_breakage.py keeps the two in lockstep.
SCHEMA_PROPERTY_TYPES: tuple[str, ...] = (
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
    "null",
)


class Task(BaseModel):
    """A single replayable task in a suite."""

    id: str
    capability: str
    prompt: str
    # The function name the model is expected to call. ``None`` means the
    # ``tool_call_success`` signal does not apply to this task.
    expected_tool_call: str | None = None
    # When True (default), a detected refusal is breakage for this task. Set
    # False when a refusal is acceptable or expected; the refusal signal then
    # stays False and the delta map no longer reports it as a regression.
    expected_no_refusal: bool = True
    # Optional JSON-schema-like contract; required keys are checked against
    # the emitted ``tool_calls[].function.arguments`` payload, and declared
    # ``properties[<key>].type`` / ``properties[<key>].enum`` tighten the
    # check to value types and allowed values.
    expected_schema: dict[str, Any] | None = None
    # OpenAI-compatible tool definitions sent in the request body.
    tools: list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    turn_idx: int = 0

    @field_validator("expected_schema")
    @classmethod
    def _validate_expected_schema(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Reject declarations the detector cannot interpret.

        The suite is the authoritative declaration of what the runtime checks.
        An unparseable declaration used to be treated as "not checkable" and
        silently disabled a check (or, for a scalar ``required``, turned every
        valid response into a violation). Failing here surfaces the config
        error at load time through the CLI's exit-2 contract instead.
        """
        if value is None:
            return None
        required = value.get("required")
        if required is not None and (
            not isinstance(required, list)
            or not all(isinstance(key, str) for key in required)
        ):
            raise ValueError("expected_schema.required must be a list of strings")
        properties = value.get("properties")
        if properties is None:
            return value
        if not isinstance(properties, dict):
            raise ValueError("expected_schema.properties must be a mapping")
        for name, spec in properties.items():
            if not isinstance(spec, dict):
                raise ValueError(
                    f"expected_schema.properties.{name} must be a mapping"
                )
            declared = spec.get("type")
            if declared is not None and declared not in SCHEMA_PROPERTY_TYPES:
                raise ValueError(
                    f"expected_schema.properties.{name}.type must be one of "
                    f"{', '.join(SCHEMA_PROPERTY_TYPES)}, got {declared!r}"
                )
            enum = spec.get("enum")
            if enum is not None and not isinstance(enum, list):
                raise ValueError(
                    f"expected_schema.properties.{name}.enum must be a list"
                )
        return value


class Suite(BaseModel):
    """A named collection of tasks."""

    name: str
    description: str | None = None
    tasks: list[Task] = Field(default_factory=list)


def load_suite(path: str | Path) -> Suite:
    """Load a suite from a YAML file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Suite.model_validate(data)
