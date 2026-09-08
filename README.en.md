**English** | [简体中文](README.md)

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/hero-dark.svg">
  <img src="assets/presentation/hero-light.svg" width="1000" alt="Replay fixed suites, align two trajectories and summarize changes in tool-call matching, refusal signals and argument checks by capability.">
</picture>

**Replay fixed suites, align two trajectories and summarize changes in tool-call matching, refusal signals and argument checks by capability.**

`v0.1.0` · `Python 3.12+` · [MIT](LICENSE)

[Website](https://regatlas.lei6393.com) · [Demo record](docs/demo-results.json)

## Why use it

After a model change, a general impression of answers may not reveal which tasks changed. regatlas records expectations in a suite, computes explicit Boolean signals for each response and aligns by task ID and turn, preserving a path from aggregate deltas to individual responses.

## Architecture

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/architecture-dark.svg">
  <img src="assets/presentation/architecture-light.svg" width="1000" alt="suite loads YAML; replay receives service or RecordingClient responses; breakage computes signals and creates Spans. align pairs `(task_id, turn_idx)` and delta aggregates candidate minus baseline by capability. Reports contain Markdown and JSON. A signed delta is a positive or negative numeric difference, not a cryptographic signature.">
</picture>

suite loads YAML; replay receives service or RecordingClient responses; breakage computes signals and creates Spans. align pairs `(task_id, turn_idx)` and delta aggregates candidate minus baseline by capability. Reports contain Markdown and JSON. A signed delta is a positive or negative numeric difference, not a cryptographic signature.

Source entry points: [src/regatlas/cli.py](src/regatlas/cli.py) · [src/regatlas/replay.py](src/regatlas/replay.py) · [src/regatlas/suite.py](src/regatlas/suite.py) · [src/regatlas/breakage.py](src/regatlas/breakage.py) · [src/regatlas/align.py](src/regatlas/align.py) · [src/regatlas/delta.py](src/regatlas/delta.py) · [suites/toolcalling.yaml](suites/toolcalling.yaml)

## Install

Requires Python 3.12+ and uv. Response fixtures run offline; live replay requires a configured endpoint and key.

```bash
git clone https://github.com/SuperMarioYL/regatlas.git
cd regatlas
uv venv --python 3.12
uv pip install --python .venv/bin/python -e .
```

## Quickstart

Replay six tasks from two shipped response fixtures. Model names in filenames are historical fixture labels, not verified model measurements. Percentage displays represent differences in rates and should be read as percentage-point changes.

```bash
.venv/bin/python examples/presentation-demo.py
```

Complete inputs and execution steps are included in the commands above and the [demo record](docs/demo-results.json).

## Usage

```bash
.venv/bin/regatlas run --suite suites/toolcalling.yaml --models opus-4,opus-5 --recordings tests/fixtures
.venv/bin/regatlas diff --from traj_opus-4.jsonl --to traj_opus-5.jsonl --out diff.json
.venv/bin/regatlas report --diff diff.json --out atlas.md
```
These commands still use fixtures. Live `replay --suite ... --model NAME` calls a service when --recording is absent. `run --out-dir` selects the trajectory directory; diff’s --baseline/--candidate alias source/target.

## Recorded demo

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/process-dark.svg">
  <img src="assets/presentation/process-light.svg" width="1000" alt="Replay six tasks from two shipped response fixtures. Model names in filenames are historical fixture labels, not verified model measurements. Percentage displays represent differences in rates and should be read as percentage-point changes.">
</picture>

### Generate the delta map

Produce deltas for tool matching and argument checks across six tasks without executing named tools.

```text
$ .venv/bin/python examples/presentation-demo.py
## regatlas delta map

**baseline-fixture → candidate-fixture** · suite `toolcalling` · 6 tasks across 1 capability.

| Capability | tool-call Δ | refusal Δ | schema Δ | n |
|---|---|---|---|---|
| tool-calling | ✗ -33% | · 0% | ✗ +17% | 6 |

<!-- raw DeltaMap JSON — the portable regression artifact -->
```json
{
  "tool-calling": {
    "tool_call_success_delta": -0.3333333333333333,
    "refusal_detected_delta": 0.0,
    "schema_violation_delta": 0.16666666666666666,
    "n_tasks": 6
  }
}
```
```

## Capabilities and integration

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/integrations-dark.svg">
  <img src="assets/presentation/integrations-light.svg" width="1000" alt="The repository includes toolcalling and refusal suites. Tool success checks whether the expected tool name was emitted; it does not execute the tool. Schema checks cover JSON and required fields, not full JSON Schema validation. Refusal detection uses English and Chinese phrase lists.">
</picture>

The repository includes toolcalling and refusal suites. Tool success checks whether the expected tool name was emitted; it does not execute the tool. Schema checks cover JSON and required fields, not full JSON Schema validation. Refusal detection uses English and Chinese phrase lists.



## Configuration

Endpoint variables are `REGATLAS_<NAME>_BASE_URL`, `_API_KEY` and `_MODEL`, using the alias uppercased after removing non-alphanumerics. Suites specify capability, expected_tool_call and expected_schema.required. `--recording` selects one file; --recordings selects an alias-named directory.

## Roadmap and scope

Current capabilities cover single-turn suites, trajectory alignment and capability reports. Hosted scheduling, further export adapters, multi-turn analysis and richer validation remain future directions.

- Rule signals do not establish overall quality or safety; whether additional refusals are regressions depends on task expectations.
- The demo calls no real model and cannot rank models or establish a version regression.

![Terminal recording](assets/demo.gif) · [Recording script](docs/demo.tape)

## License

[MIT](LICENSE)
