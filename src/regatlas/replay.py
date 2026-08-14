"""Replay engine — runs a suite against an OpenAI-compatible endpoint.

Two client implementations share the same ``complete(task)`` contract:

* ``ReplayClient`` — a real ``httpx`` client that POSTs to
  ``{base_url}/v1/chat/completions`` and extracts ``choices[0].message``
  (``content`` + ``tool_calls`` only; per-vendor extras like
  ``reasoning_content`` are ignored).
* ``RecordingClient`` — reads canned responses from a JSON fixture keyed by
  ``task_id`` so demos, CI, and tests run offline without API keys.

Model endpoints are resolved from env vars ``REGATLAS_<NAME>_BASE_URL`` and
``REGATLAS_<NAME>_API_KEY`` where ``<NAME>`` is the alias upper-cased and
stripped of non-alphanumerics (``opus-4`` -> ``OPUS4``).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from regatlas.breakage import Breakage, compute_breakage
from regatlas.suite import Suite, Task
from regatlas.trajectory import Response, Span

# Built-in aliases surfaced by ``regatlas --list-models``. Each resolves its
# endpoint from env vars at call time so no secrets live in source.
DEFAULT_MODELS: tuple[str, ...] = (
    "opus-4",
    "opus-5",
    "glm-4.5",
    "glm-4.6",
    "deepseek-v3",
    "deepseek-v3.5",
    "qwen-2.5",
    "qwen-3",
)


def env_name(alias: str) -> str:
    """``opus-4`` -> ``OPUS4``; ``glm-4.6`` -> ``GLM46``."""
    return re.sub(r"[^A-Z0-9]", "", alias.upper())


class ModelEndpoint(BaseModel):
    """A resolved model endpoint (base URL + key may be unset)."""

    name: str
    base_url: str | None = None
    api_key: str | None = None
    model: str  # served model name sent in the request body

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


def resolve_endpoint(alias: str) -> ModelEndpoint:
    """Resolve an endpoint alias from env vars."""
    env = env_name(alias)
    base = os.environ.get(f"REGATLAS_{env}_BASE_URL")
    key = os.environ.get(f"REGATLAS_{env}_API_KEY")
    served = os.environ.get(f"REGATLAS_{env}_MODEL", alias)
    return ModelEndpoint(name=alias, base_url=base, api_key=key, model=served)


def list_endpoints() -> list[ModelEndpoint]:
    """List all built-in model aliases with their env-var resolution status."""
    return [resolve_endpoint(alias) for alias in DEFAULT_MODELS]


class Client(Protocol):
    """The replay client contract."""

    model_version: str

    def complete(self, task: Task) -> dict[str, Any]: ...


class ReplayClient:
    """Live ``httpx`` client against an OpenAI-compatible endpoint."""

    def __init__(self, endpoint: ModelEndpoint, timeout: float = 60.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    @property
    def model_version(self) -> str:
        return self.endpoint.name

    def complete(self, task: Task) -> dict[str, Any]:
        ep = self.endpoint
        if not ep.base_url:
            raise RuntimeError(
                f"no base URL configured for model '{ep.name}'. Set "
                f"REGATLAS_{env_name(ep.name)}_BASE_URL (and _API_KEY), or "
                f"replay with --recording for an offline run."
            )
        messages = [{"role": "user", "content": task.prompt}]
        payload: dict[str, Any] = {
            "model": ep.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": task.max_tokens or 1024,
        }
        if task.tools:
            payload["tools"] = task.tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if ep.api_key:
            headers["Authorization"] = f"Bearer {ep.api_key}"
        url = ep.base_url.rstrip("/") + "/v1/chat/completions"
        with httpx.Client(timeout=self.timeout) as session:
            resp = session.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        message = choices[0].get("message") if choices else {}
        if message is None:
            message = {}
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        return {"content": content, "tool_calls": tool_calls}


class RecordingClient:
    """Offline client backed by a JSON fixture keyed by ``task_id``."""

    def __init__(self, responses: dict[str, dict[str, Any]], model_version: str) -> None:
        self.responses = responses
        self._model_version = model_version

    @property
    def model_version(self) -> str:
        return self._model_version

    @classmethod
    def from_file(cls, path: str | Path, model_version: str) -> "RecordingClient":
        with Path(path).open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"recording file {path} must be a JSON object keyed by task_id")
        return cls(data, model_version=model_version)

    def complete(self, task: Task) -> dict[str, Any]:
        entry = self.responses.get(task.id)
        if entry is None:
            raise KeyError(f"no recorded response for task '{task.id}' in this recording")
        return {
            "content": entry.get("content"),
            "tool_calls": entry.get("tool_calls"),
        }


def replay_suite(
    suite: Suite,
    client: Client,
    *,
    run_id: str | None = None,
) -> list[Span]:
    """Replay every task in ``suite`` through ``client`` and build spans.

    Each task becomes one capability-tagged span with breakage signals. Network
    or fixture errors are captured per-span (``error`` field) rather than
    aborting the run, so a partial trajectory is still attributable.
    """
    run_id = run_id or f"regatlas-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    spans: list[Span] = []
    for task in suite.tasks:
        request = {
            "model": client.model_version,
            "messages": [{"role": "user", "content": task.prompt}],
            "tools": task.tools,
            "max_tokens": task.max_tokens or 1024,
        }
        try:
            result = client.complete(task)
            response = Response(
                content=result.get("content"),
                tool_calls=result.get("tool_calls"),
            )
            breakage = compute_breakage(task, result)
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 — per-span capture
            response = Response()
            breakage = Breakage(
                tool_call_success=detect_failure_success(task),
                refusal_detected=False,
                schema_violation=False,
            )
            error = f"{type(exc).__name__}: {exc}"
        spans.append(
            Span(
                run_id=run_id,
                model_version=client.model_version,
                task_id=task.id,
                turn_idx=task.turn_idx,
                capability=task.capability,
                request=request,
                response=response,
                breakage=breakage,
                error=error,
            )
        )
    return spans


def detect_failure_success(task: Task) -> bool | None:
    """On error, a tool-call expectation is treated as not met."""
    if task.expected_tool_call is None:
        return None
    return False
