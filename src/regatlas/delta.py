"""Delta aggregation — the per-capability regression atlas primitive.

Aggregates a list of ``SpanDiff`` records by ``capability`` into a
``DeltaMap``: the mean signed per-signal delta over the spans in that
capability. Because each per-span delta is in ``{-1, 0, +1}``, the mean is a
fraction in ``[-1, 1]`` — e.g. ``-0.33`` reads as "tool-call success dropped
33 percentage points", ``+0.50`` reads as "refusal rate rose 50 points".

The delta map is the portable artifact a release-gating team pastes into a
PR comment to prove a model swap's regression. It is also the format a future
hosted tier will store and re-schedule across every nightly drop.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Iterable

from pydantic import BaseModel

from regatlas.align import SIGNALS, SpanDiff


class CapabilityDelta(BaseModel):
    """Per-capability aggregate of the three breakage-signal deltas."""

    tool_call_success_delta: float | None = None
    refusal_detected_delta: float | None = None
    schema_violation_delta: float | None = None
    n_tasks: int = 0


DeltaMap = dict[str, CapabilityDelta]


def _mean(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(span_diffs: Iterable[SpanDiff]) -> DeltaMap:
    """Aggregate spans by capability into a delta map."""
    by_capability: dict[str, list[SpanDiff]] = defaultdict(list)
    for diff in span_diffs:
        by_capability[diff.capability].append(diff)

    delta_map: DeltaMap = {}
    for capability, diffs in by_capability.items():
        n = len(diffs)
        tool_call = [
            d.deltas["tool_call_success"]
            for d in diffs
            if d.deltas["tool_call_success"] is not None
        ]
        refusal = [
            d.deltas["refusal_detected"]
            for d in diffs
            if d.deltas["refusal_detected"] is not None
        ]
        schema = [
            d.deltas["schema_violation"]
            for d in diffs
            if d.deltas["schema_violation"] is not None
        ]
        delta_map[capability] = CapabilityDelta(
            tool_call_success_delta=_mean(tool_call) if tool_call else None,
            refusal_detected_delta=_mean(refusal) if refusal else None,
            schema_violation_delta=_mean(schema) if schema else None,
            n_tasks=n,
        )
    return delta_map


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.0f}%".replace("+0%", "0%")


def _marker(signal: str, value: float | None) -> str:
    """Direction glyph: regression (✗), improvement (✓), or flat (·)."""
    if value is None:
        return "·"
    if value == 0:
        return "·"
    # tool_call_success: lower is worse (regression).
    # refusal_detected / schema_violation: higher is worse (regression).
    if signal == "tool_call_success":
        return "✗" if value < 0 else "✓"
    return "✗" if value > 0 else "✓"


def render_markdown(
    delta_map: DeltaMap,
    *,
    from_model: str | None,
    to_model: str | None,
    suite_name: str | None,
    total_tasks: int | None = None,
) -> str:
    """Render the delta map as a paste-into-PR markdown table + raw JSON."""
    from_label = from_model or "?"
    to_label = to_model or "?"
    suite_label = suite_name or "?"
    n_caps = len(delta_map)
    n_tasks = total_tasks if total_tasks is not None else sum(
        cap.n_tasks for cap in delta_map.values()
    )

    lines: list[str] = []
    lines.append("## regatlas delta map")
    lines.append("")
    lines.append(
        f"**{from_label} → {to_label}** · suite `{suite_label}` · "
        f"{n_tasks} tasks across {n_caps} capabilit{'y' if n_caps == 1 else 'ies'}."
    )
    lines.append("")
    lines.append("| Capability | tool-call Δ | refusal Δ | schema Δ | n |")
    lines.append("|---|---|---|---|---|")
    for capability in sorted(delta_map):
        cap = delta_map[capability]
        tc = cap.tool_call_success_delta
        rf = cap.refusal_detected_delta
        sc = cap.schema_violation_delta
        lines.append(
            f"| {capability} "
            f"| {_marker('tool_call_success', tc)} {_fmt_pct(tc)} "
            f"| {_marker('refusal_detected', rf)} {_fmt_pct(rf)} "
            f"| {_marker('schema_violation', sc)} {_fmt_pct(sc)} "
            f"| {cap.n_tasks} |"
        )
    lines.append("")
    lines.append("<!-- raw DeltaMap JSON — the portable regression artifact -->")
    raw = {cap: delta.model_dump() for cap, delta in delta_map.items()}
    lines.append("```json")
    lines.append(json.dumps(raw, ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines)
