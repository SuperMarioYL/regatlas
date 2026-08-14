#!/usr/bin/env bash
# regatlas quickstart — the full pipeline, offline, no API keys required.
# Runs the bundled tool-calling suite against two recorded model versions,
# diffs them, and prints the per-capability regression atlas.
set -euo pipefail

regatlas run --suite suites/toolcalling.yaml --models opus-4,opus-5 --recordings tests/fixtures
regatlas diff --baseline opus-4 --candidate opus-5 --out diff.json
regatlas report --diff diff.json
