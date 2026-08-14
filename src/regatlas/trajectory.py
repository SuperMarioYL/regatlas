"""Trajectory model — the append-only JSONL of capability-tagged spans.

A trajectory file (``traj_<model>.jsonl``) is one ``Span`` per line, written by
``replay`` and read by ``diff``. Each span carries the request, the response
(``content`` + ``tool_calls`` extracted from the OpenAI-compatible message
shape), and the pre-computed ``breakage`` signals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from regatlas.breakage import Breakage


class Response(BaseModel):
    """The slice of ``choices[0].message`` that regatlas reasons over."""

    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class Span(BaseModel):
    """One replayed task turn — the unit of trajectory alignment."""

    run_id: str
    model_version: str
    task_id: str
    turn_idx: int = 0
    capability: str
    request: dict[str, Any]
    response: Response
    breakage: Breakage
    error: str | None = None


def span_to_jsonl(span: Span) -> str:
    return span.model_dump_json()


def write_trajectory(
    path: str | Path | None, spans: Iterable[Span]
) -> None:
    """Write spans as JSONL.

    ``path`` of ``None`` or ``"-"`` writes to stdout so the mvp happy path
    (``regatlas replay ... > traj.jsonl``) works.
    """
    lines = [span_to_jsonl(s) for s in spans]
    payload = "\n".join(lines) + ("\n" if lines else "")
    if path is None or str(path) == "-":
        sys.stdout.write(payload)
    else:
        Path(path).write_text(payload, encoding="utf-8")


def read_trajectory(path: str | Path) -> list[Span]:
    """Read a trajectory JSONL file into a list of spans."""
    p = Path(path)
    spans: list[Span] = []
    text = p.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        spans.append(Span.model_validate_json(line))
    return spans
