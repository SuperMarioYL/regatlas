"""Export adapters — land a regatlas diff in existing trace stores.

``regatlas export --diff diff.json --format <fmt>`` converts a diff document
(produced by ``regatlas diff``) into a payload for an existing trace store or a
standalone JSON artifact. All adapters are offline: they emit static files the
user imports or POSTs, so there are no network calls and no new dependencies.

Formats and their mapping (documented contract, stable field names):

* ``json`` — the raw ``DeltaMap``: ``{capability: {tool_call_success_delta,
  refusal_detected_delta, schema_violation_delta, n_tasks}}``, identical to
  the JSON block ``regatlas report`` embeds in its markdown, as a standalone
  file. This is the portable regression artifact itself.
* ``langsmith`` — JSONL, one line per ``SpanDiff`` formatted as a LangSmith
  run: ``id`` (deterministic uuid5 of the span identity), ``name``
  ``regatlas:diff:<task_id>``, ``run_type`` "chain", ``inputs`` the span
  identity (task_id, turn_idx, capability, from_model, to_model), ``outputs``
  the two breakage snapshots plus the signed deltas, and one ``feedback``
  entry per non-null delta (``regatlas.<signal>_delta`` keys, ``score`` in
  {-1, 0, +1}). Import the file as a run export or POST each line to the
  runs API.
* ``langfuse`` — one ingestion-batch document: a ``trace-create`` per
  capability (``regatlas:atlas:<capability>``), one ``observation-create``
  per span diff (type SPAN, input = span identity, output = deltas plus the
  breakage snapshots), and one ``score-create`` per non-null signed delta
  attached to the capability trace. POST the ``batch`` list as an ingestion
  batch.

The vendor payloads carry regatlas-owned fields only; fields the target adds
server-side (timestamps, project ids, API keys) are left to the import step.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Iterable

from regatlas.align import SIGNALS, SpanDiff
from regatlas.delta import aggregate


def _stable_id(*parts: str) -> str:
    """Deterministic uuid so repeated exports of one diff are idempotent."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "regatlas:" + ":".join(parts)))


def _span_identity(diff: SpanDiff) -> dict:
    return {
        "task_id": diff.task_id,
        "turn_idx": diff.turn_idx,
        "capability": diff.capability,
        "from_model": diff.from_model,
        "to_model": diff.to_model,
    }


def _scores(diff: SpanDiff) -> list[dict]:
    """One feedback/score entry per non-null signed delta."""
    return [
        {"key": f"regatlas.{signal}_delta", "score": value}
        for signal in SIGNALS
        if (value := diff.deltas.get(signal)) is not None
    ]


def export_langsmith(span_diffs: Iterable[SpanDiff]) -> str:
    """Render one LangSmith run per SpanDiff as JSONL."""
    lines: list[str] = []
    for diff in span_diffs:
        run = {
            "id": _stable_id(
                str(diff.from_model), str(diff.to_model), diff.task_id, str(diff.turn_idx)
            ),
            "name": f"regatlas:diff:{diff.task_id}",
            "run_type": "chain",
            "inputs": _span_identity(diff),
            "outputs": {
                "from_breakage": diff.from_breakage.model_dump(),
                "to_breakage": diff.to_breakage.model_dump(),
                "deltas": dict(diff.deltas),
            },
            "feedback": _scores(diff),
        }
        lines.append(json.dumps(run, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def export_langfuse(span_diffs: Iterable[SpanDiff]) -> str:
    """Render one Langfuse ingestion batch for the whole diff document."""
    by_capability: dict[str, list[SpanDiff]] = defaultdict(list)
    for diff in span_diffs:
        by_capability[diff.capability].append(diff)

    batch: list[dict] = []
    for capability, diffs in sorted(by_capability.items()):
        trace_id = _stable_id("atlas", capability)
        batch.append(
            {
                "type": "trace-create",
                "body": {"id": trace_id, "name": f"regatlas:atlas:{capability}"},
            }
        )
        for diff in diffs:
            batch.append(
                {
                    "type": "observation-create",
                    "body": {
                        "id": _stable_id(
                            "obs",
                            str(diff.from_model),
                            str(diff.to_model),
                            diff.task_id,
                            str(diff.turn_idx),
                        ),
                        "traceId": trace_id,
                        "type": "SPAN",
                        "name": f"regatlas:diff:{diff.task_id}",
                        "input": _span_identity(diff),
                        "output": {
                            "deltas": dict(diff.deltas),
                            "from_breakage": diff.from_breakage.model_dump(),
                            "to_breakage": diff.to_breakage.model_dump(),
                        },
                    },
                }
            )
            for score in _scores(diff):
                batch.append(
                    {
                        "type": "score-create",
                        "body": {
                            "id": _stable_id(
                                "score",
                                str(diff.from_model),
                                str(diff.to_model),
                                diff.task_id,
                                str(diff.turn_idx),
                                score["key"],
                            ),
                            "traceId": trace_id,
                            "name": score["key"],
                            "value": score["score"],
                        },
                    }
                )
    return json.dumps({"batch": batch}, ensure_ascii=False, indent=2) + "\n"


def export_json(span_diffs: Iterable[SpanDiff]) -> str:
    """Render the standalone DeltaMap artifact (report's embedded JSON block)."""
    delta_map = aggregate(span_diffs)
    raw = {capability: delta.model_dump() for capability, delta in delta_map.items()}
    return json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
