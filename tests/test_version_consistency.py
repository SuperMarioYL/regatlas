"""Version lockstep — every surface must report the same version.

Guards the surfaces swept for each release: VERSION, pyproject.toml,
regatlas.__version__, both README hero lines, web/site.json meta and footer,
and the CHANGELOG sections. The installed-CLI check shells out to the
`regatlas` binary and is skipped on runners where it is not on PATH.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import tomllib

from regatlas import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "0.2.0"


def test_version_file() -> None:
    assert (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip() == EXPECTED_VERSION


def test_pyproject_version() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    assert data["project"]["version"] == EXPECTED_VERSION


def test_dunder_version() -> None:
    assert __version__ == EXPECTED_VERSION


def test_readme_hero_lines() -> None:
    for name in ("README.md", "README.en.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert f"`v{EXPECTED_VERSION}` · `Python 3.12+` · [MIT](LICENSE)" in text, name


def test_web_site_json() -> None:
    site = json.loads((REPO_ROOT / "web" / "site.json").read_text(encoding="utf-8"))
    assert site["meta"]["content_version"] == EXPECTED_VERSION
    assert site["footer"]["tag"].startswith(f"{EXPECTED_VERSION} ·")


def test_changelog_sections() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for section in ("[0.1.0]", "[0.2.0]"):
        assert f"## {section}" in text
        assert re.search(rf"^\[{re.escape(section[1:-1])}\]: .+$", text, re.MULTILINE)


class InstalledCliVersionTest(unittest.TestCase):
    """`regatlas --version` must match; skipped when the binary is absent."""

    def test_installed_cli_reports_version(self) -> None:
        binary = shutil.which("regatlas")
        if not binary:
            self.skipTest("regatlas binary not on PATH")
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(f"regatlas {EXPECTED_VERSION}", result.stdout)
