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
from pydantic import BaseModel, Field


class Task(BaseModel):
    """A single replayable task in a suite."""

    id: str
    capability: str
    prompt: str
    # The function name the model is expected to call. ``None`` means the
    # ``tool_call_success`` signal does not apply to this task.
    expected_tool_call: str | None = None
    # When True, a refusal on this task is a regression.
    expected_no_refusal: bool = True
    # Optional JSON-schema-like contract; required keys are checked against
    # the emitted ``tool_calls[].function.arguments`` payload.
    expected_schema: dict[str, Any] | None = None
    # OpenAI-compatible tool definitions sent in the request body.
    tools: list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    turn_idx: int = 0


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
