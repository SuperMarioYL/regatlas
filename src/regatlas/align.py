"""Aligner — joins two trajectories by span key and emits signed deltas.

Spans are paired by ``(task_id, turn_idx)`` — the span-semantic key that stays
stable across a version swap. For each pair a ``SpanDiff`` carries the two
breakage snapshots and three signed per-signal deltas in ``{-1, 0, +1, None}``:

* ``tool_call_success`` — ``True`` is good (success). A drop True->False is
  ``-1`` (regression); a rise False->True is ``+1`` (improvement). ``None``
  when the signal is not applicable on either side.
* ``refusal_detected`` — ``True`` is bad (refusal). A rise False->True is
  ``+1`` (regression); a drop True->False is ``-1`` (improvement).
* ``schema_violation`` — ``True`` is bad. Same polarity as refusal.

The polarity convention matches the delta map: a negative
``tool_call_success_delta`` is a regression, a positive
``refusal_detected_delta`` / ``schema_violation_delta`` is a regression.
"""

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel

from regatlas.breakage import Breakage
from regatlas.trajectory import Span


def _as_bool_int(value: bool | None) -> int | None:
    """Coerce a tri-state bool to ``0/1`` or ``None``."""
    if value is None:
        return None
    return 1 if value else 0


def signed_delta(to_value: bool | None, from_value: bool | None) -> int | None:
    """Signed delta ``to - from`` in ``{-1, 0, +1}``; ``None`` if either side
    is not applicable."""
    t = _as_bool_int(to_value)
    f = _as_bool_int(from_value)
    if t is None or f is None:
        return None
    if t == f:
        return 0
    return 1 if t > f else -1


class SpanDiff(BaseModel):
    """One paired span across two model versions."""

    task_id: str
    turn_idx: int
    capability: str
    from_model: str | None = None
    to_model: str | None = None
    from_breakage: Breakage
    to_breakage: Breakage
    deltas: dict[str, int | None]


SIGNALS: tuple[str, ...] = (
    "tool_call_success",
    "refusal_detected",
    "schema_violation",
)


def align_spans(
    from_spans: Iterable[Span],
    to_spans: Iterable[Span],
) -> list[SpanDiff]:
    """Pair spans by ``(task_id, turn_idx)`` and emit per-signal deltas.

    A span present on only one side is paired with an empty breakage so the
    delta still records the appearance/disappearance of a capability.
    """
    from_index = {(s.task_id, s.turn_idx): s for s in from_spans}
    to_index = {(s.task_id, s.turn_idx): s for s in to_spans}
    keys = sorted(set(from_index) | set(to_index))

    diffs: list[SpanDiff] = []
    for key in keys:
        left = from_index.get(key)
        right = to_index.get(key)
        from_breakage = left.breakage if left else Breakage()
        to_breakage = right.breakage if right else Breakage()
        capability = (right or left).capability if (right or left) else ""
        deltas = {
            "tool_call_success": signed_delta(
                to_breakage.tool_call_success,
                from_breakage.tool_call_success,
            ),
            "refusal_detected": signed_delta(
                to_breakage.refusal_detected,
                from_breakage.refusal_detected,
            ),
            "schema_violation": signed_delta(
                to_breakage.schema_violation,
                from_breakage.schema_violation,
            ),
        }
        diffs.append(
            SpanDiff(
                task_id=key[0],
                turn_idx=key[1],
                capability=capability,
                from_model=left.model_version if left else None,
                to_model=right.model_version if right else None,
                from_breakage=from_breakage,
                to_breakage=to_breakage,
                deltas=deltas,
            )
        )
    return diffs
