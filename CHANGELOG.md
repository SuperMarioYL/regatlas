# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-11

### Fixed
- Bad input files no longer crash with a raw traceback and exit 1: missing or
  unreadable recordings / diff documents / trajectory files, non-object
  recording and diff documents, malformed suite YAML, and trajectory JSONL
  that fails `Span` validation now print a one-line `error:` to stderr and
  exit 2 across `replay`, `run`, `diff`, and `report` — matching the CLI's
  existing unconfigured-endpoint error contract.
- `regatlas report --diff` no longer raises `KeyError: 'tool_call_success'`
  on a schema-valid diff document whose span `deltas` omit a signal key
  (e.g. a hand-trimmed paste-into-PR artifact); missing keys now behave like
  an explicit null — excluded from the capability mean and rendered as an
  em-dash.

### Added
- `regatlas export --diff diff.json --format langsmith|langfuse|json` (v0.2
  roadmap item "export adapters"): converts a diff document into a LangSmith
  run-export JSONL (one run per span pair, one feedback entry per non-null
  signed delta, deterministic ids), a Langfuse ingestion batch (one trace per
  capability, one SPAN observation per span pair, score events for the
  deltas), or the standalone `DeltaMap` JSON artifact identical to the block
  `report` embeds in its markdown. All adapters emit offline static payloads.

### Changed
- Version lockstep bump to 0.2.0 across every surface: `VERSION`,
  `pyproject.toml`, `regatlas.__version__` (drives `--version`), both README
  hero lines, and `web/site.json` (`meta.content_version` and footer tag).

## [0.1.0] - 2026-08-15

### Added
- `regatlas replay --suite --model` — replays a fixed task-suite against an
  OpenAI-compatible `/v1/chat/completions` endpoint and emits one
  capability-tagged `Span` per task to JSONL, with machine-checkable breakage
  signals (`tool_call_success`, `refusal_detected`, `schema_violation`)
  populated by the `breakage` detectors.
- `regatlas run --suite --models` — convenience wrapper that replays a suite
  for multiple model versions and writes one trajectory file per model.
- `regatlas diff --from/--to` (aliases `--baseline/--candidate`) — aligns
  trajectories by `(task_id, turn_idx)` and emits a signed per-signal
  `SpanDiff` document.
- `regatlas report --diff` — aggregates `SpanDiff` records by capability into
  a per-capability delta map rendered as a markdown table plus the raw
  `DeltaMap` JSON.
- `regatlas --list-models` — lists configured model endpoints and the
  `REGATLAS_<NAME>_BASE_URL` / `_API_KEY` env-var resolution status.
- Bundled suites `suites/toolcalling.yaml` and `suites/refusal.yaml` ship
  in-repo so the happy path works with zero user authoring.
- Offline replay mode via `--recording` / `--recordings` reads canned model
  responses from a JSON fixture, so demos and CI run without API keys.
- Pytest suite covering each milestone (breakage, replay, align, delta, CLI
  integration) with offline recorded responses.
- GitHub Actions: `test.yml` (pytest on push/PR), `release.yml` (build dist on
  tag, opt-in PyPI trusted publishing), `demo.yml` (re-render the demo GIF).

[0.1.0]: https://github.com/SuperMarioYL/regatlas/releases/tag/v0.1.0
[0.2.0]: https://github.com/SuperMarioYL/regatlas/releases/tag/v0.2.0
