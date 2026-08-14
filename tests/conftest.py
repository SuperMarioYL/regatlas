"""Shared test helpers."""
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
SUITES = Path(__file__).parent.parent / "suites"


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def suite_path(name: str) -> Path:
    if not name.endswith(".yaml"):
        name = f"{name}.yaml"
    return SUITES / name
