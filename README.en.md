<div align="right"><sub><b>English</b>&nbsp;&nbsp;⇄&nbsp;&nbsp;<a href="./README.md">简体中文</a></sub></div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
  <img src="./assets/hero-light.svg" width="880" alt="regatlas — model-version regression-attribution CLI">
</picture>

<p align="center"><sub>The model-version regression-attribution CLI that turns "Opus 5 feels worse" into "tool-calling −14%, refusal +28%".</sub></p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/SuperMarioYL/regatlas?color=0071E3&label=license" alt="license"></a>
  &nbsp;<a href="https://github.com/SuperMarioYL/regatlas/releases"><img src="https://img.shields.io/github/v/release/SuperMarioYL/regatlas?label=release&color=10A37F" alt="release"></a>
  &nbsp;<a href="https://github.com/SuperMarioYL/regatlas/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/regatlas/test.yml?branch=main&label=ci" alt="ci"></a>
  &nbsp;<img src="https://img.shields.io/badge/python-3.12%2B-5E5CE6" alt="python">
</p>

<p align="center"><b>regatlas replays a fixed task-suite across model versions, aligns trajectories by span semantics, and maps per-capability deltas via machine-checkable breakage signals — so a version swap's silent regressions become provable and attributable.</b></p>

---

## Contents

- [Architecture](#architecture)
- [Why this exists](#why-this-exists)
- [Install](#install)
- [Quickstart](#quickstart)
- [Usage](#usage)
- [Demo](#demo)
- [Configuration](#configuration)
- [Pricing](#pricing)
- [Roadmap](#roadmap)
- [License](#license)

<h2><img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Architecture</h2>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
  <img src="./assets/atlas-light.svg" width="880" alt="architecture: Task Suite → Replay · Breakage → Delta Map">
</picture>

A single-process CLI — no daemons, no microservices. One binary-equivalent (`uv tool install`) and three subcommands: `replay` runs the task-suite and emits breakage-tagged trajectories; `diff` aligns two trajectories by `(task_id, turn_idx)` and emits signed deltas; `report` aggregates them into a per-capability delta map.

<h2><img src="https://api.iconify.design/tabler:bulb.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Why this exists</h2>

When an agent swaps a model version — Opus-4 to Opus-5, GLM-4.5 to 4.6 — behavior drifts in ways the API contract never advertises: a tool call starts failing, refusal rate climbs, a planning step collapses. The "Why does Opus 5 feel worse?" thread hit the HN front page because the perception is widespread and sharp — but the version-bump review today is "eyeball a few traces, feel it's worse, ship anyway."

regatlas makes the action attributable: replay a fixed task-suite and use three **machine-checkable** breakage signals (`tool_call_success` — did the emitted tool name match the expected one; `refusal_detected` — does content match a zh+en refusal lexicon; `schema_violation` — do arguments parse as JSON and satisfy a declared schema) to produce a per-capability delta. Without this primitive, regression stays perception-only; with it, the delta map is provable evidence you can paste into a PR.

> How it differs from existing tooling: eval platforms (LangSmith / Langfuse / Helicone) model traces within a single deployment, not replay-aligned across versions; contract-diff tools only see the API surface, so a worse tool-call rate under the same schema is invisible to them. regatlas's moat is the replay + machine-checkable breakage layer — the thing an observability platform would integrate rather than rebuild.

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Install</h2>

```bash
# Requires Python 3.12+
uv tool install regatlas        # or: pip install regatlas
```

The repo ships bundled suites `suites/toolcalling.yaml` and `suites/refusal.yaml`, plus offline recorded responses (`tests/fixtures/*.responses.json`), so the path from `git clone` to a first visible result needs no API key.

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Quickstart</h2>

```bash
git clone https://github.com/SuperMarioYL/regatlas && cd regatlas
pip install -e .
regatlas run --suite suites/toolcalling.yaml --models opus-4,opus-5 --recordings tests/fixtures \
  && regatlas diff --baseline opus-4 --candidate opus-5 --out diff.json \
  && regatlas report --diff diff.json
```

<details>
<summary>sample output (report excerpt)</summary>

```
## regatlas delta map

**opus-4 → opus-5** · suite `tool-calling` · 6 tasks across 1 capability.

| Capability | tool-call Δ | refusal Δ | schema Δ | n |
|---|---|---|---|---|
| tool-calling | ✗ -33% | · 0% | ✗ +17% | 6 |
```

`✗` marks a regression direction (tool-call success dropped, or refusal / schema violation rose), `✓` an improvement, `·` flat, `—` not applicable for that task.
</details>

<h2><img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Usage</h2>

**List configured model endpoints**

```bash
regatlas --list-models
```

**Replay one model version** (live endpoint, JSONL to stdout)

```bash
export REGATLAS_OPUS4_BASE_URL=https://api.openai.com/v1
export REGATLAS_OPUS4_API_KEY=sk-...
regatlas replay --suite suites/toolcalling.yaml --model opus-4 > traj_opus-4.jsonl
```

**Replay offline** (recorded responses, no key — for CI and local demos)

```bash
regatlas replay --suite suites/toolcalling.yaml --model opus-5 \
  --recording tests/fixtures/opus-5.responses.json --out traj_opus-5.jsonl
```

**Align and emit signed deltas**

```bash
regatlas diff --from traj_opus-4.jsonl --to traj_opus-5.jsonl --out diff.json
# alias flags and bare model aliases also work (resolves to traj_<alias>.jsonl):
regatlas diff --baseline opus-4 --candidate opus-5 --out diff.json
```

**Aggregate into a per-capability delta map**

```bash
regatlas report --diff diff.json           # markdown table + raw DeltaMap JSON
regatlas report --diff diff.json --out atlas.md
```

See [`examples/quickstart.sh`](./examples/quickstart.sh) for the full script.

<h2><img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Demo</h2>

![demo](assets/demo.gif)

The GIF above is rendered from [`docs/demo.tape`](./docs/demo.tape) via vhs; `.github/workflows/demo.yml` re-renders it on demand.

<h2><img src="https://api.iconify.design/tabler:adjustments.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Configuration</h2>

Model endpoints resolve from environment variables, where `<NAME>` is the alias upper-cased and stripped of non-alphanumerics (`opus-4` → `OPUS4`, `glm-4.6` → `GLM46`):

| Variable | Type | Default | Meaning |
|---|---|---|---|
| `REGATLAS_<NAME>_BASE_URL` | str | none | OpenAI-compatible base URL (suffixed with `/v1/chat/completions`) |
| `REGATLAS_<NAME>_API_KEY` | str | none | `Authorization: Bearer <key>` header |
| `REGATLAS_<NAME>_MODEL` | str | alias | served `model` field in the request body |

`replay` also takes `--recording PATH` (a single recorded-response JSON) for offline runs; `run` takes `--recordings DIR` (files named `<alias>.responses.json`) for batch offline replay. Built-in aliases: `opus-4`, `opus-5`, `glm-4.5`, `glm-4.6`, `deepseek-v3`, `deepseek-v3.5`, `qwen-2.5`, `qwen-3`.

<h2><img src="https://api.iconify.design/tabler:credit-card.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Pricing</h2>

regatlas's commercial path targets **release-gating teams for model-version regression** — in particular the GLM / Qwen / DeepSeek labs on compressed drop cycles, and agent shops that need a regression gate before every model drop.

- **Self-hosted CLI (v0.1, MIT open source)**: run replays locally and produce a portable `DeltaMap` JSON you can paste into a PR comment to prove a version swap's regression. Self-hosted stays free.
- **Hosted scheduling tier (v0.2, paid)**: scheduled replay across every nightly drop, managed delta-storage, team workspaces, release-gate webhooks ("page PagerDuty when `refusal_detected_delta` > +15%").
  - Team plan: **¥2,000 / month / team** (≤5 seats + 50 scheduled suite-runs / month), overage **¥8 / suite-run**.
  - USD mirror for global agent shops: **$29 / seat / month**.
  - Per-run billing because model drops are bursty, not steady.

Smallest "yes, here's my credit card" path: a release-gating engineer at a CN lab runs the OSS CLI on an internal model swap, gets a delta map proving "refusal +28% on the 4.5→4.6 bump," forwards it to their lead, then asks regatlas "can you run this nightly and page my team on refusal spikes?" — that question is the v0.2 hosted-tier purchase trigger.

<h2><img src="https://api.iconify.design/tabler:map-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Roadmap</h2>

- [x] **m1 — suite replay**: `replay` runs a fixed suite against an OpenAI-compatible endpoint and emits JSONL trajectories carrying `Span` + `Breakage`.
- [x] **m2 — align + breakage**: `diff` aligns two trajectories by `(task_id, turn_idx)` and emits signed per-signal `SpanDiff` deltas.
- [x] **m3 — delta report**: `report` aggregates by capability into a delta map rendered as a markdown table + raw JSON.
- [ ] **v0.2 — hosted scheduling tier**: scheduled replay across nightly drops, delta-storage, team workspaces, release-gate webhooks.
- [ ] **v0.2 — export adapters**: `regatlas export --format langsmith` / `langfuse` so the delta map lands inside existing trajectory stores.
- [ ] **v0.2+ — native vendor Messages / Gemini API normalization** (v0.1 covers OpenAI-compatible endpoints only).
- [ ] **Future — multi-turn trajectory alignment, a judgment panel for the unmeasurable regression tail**.

<h2><img src="https://api.iconify.design/tabler:license.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> License</h2>

MIT — see [LICENSE](./LICENSE). File a regression case or a PR at [Issues](https://github.com/SuperMarioYL/regatlas/issues).

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
