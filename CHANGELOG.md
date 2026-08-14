# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
