"""regatlas CLI — the regression-atlas surface.

    regatlas --list-models
    regatlas replay --suite suites/toolcalling.yaml --model opus-4 [--recording path] [--out traj.jsonl]
    regatlas run     --suite suites/toolcalling.yaml --models opus-4,opus-5 [--recordings dir]
    regatlas diff     --from traj_v4.jsonl --to traj_v5.jsonl [--out diff.json]
    regatlas report   --diff diff.json
    regatlas export   --diff diff.json --format langsmith|langfuse|json [--out file]

``replay`` and ``run`` write JSONL trajectories; ``--recording`` / ``--recordings``
switch to an offline fixture so demos and CI run without API keys. ``diff``
accepts ``--from/--to`` or the ``--baseline/--candidate`` aliases, and resolves a
bare model alias to its default ``traj_<alias>.jsonl`` file. ``report`` prints a
markdown table plus the raw ``DeltaMap`` JSON so it can be pasted into a PR.
``export`` converts the diff into a trace-store adapter payload or the
standalone ``DeltaMap`` JSON artifact.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import typer
import yaml
from rich.console import Console
from rich.table import Table

from regatlas import __version__
from regatlas.align import SpanDiff, align_spans
from regatlas.delta import aggregate, render_markdown
from regatlas.export import export_json, export_langfuse, export_langsmith
from regatlas.replay import (
    DEFAULT_MODELS,
    RecordingClient,
    ReplayClient,
    list_endpoints,
    replay_suite,
    resolve_endpoint,
)
from regatlas.suite import load_suite
from regatlas.trajectory import read_trajectory, write_trajectory

app = typer.Typer(
    name="regatlas",
    help="Model-version regression-attribution CLI.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"regatlas {__version__}")
        raise typer.Exit()


_T = TypeVar("_T")


def _load_or_fail(action: str, loader: Callable[[], _T]) -> _T:
    """Run an input loader, converting failures into the CLI error contract.

    Bad user input — missing or unreadable files, malformed YAML/JSON/JSONL,
    documents that fail schema validation — prints a one-line ``error:`` to
    stderr and exits 2 (the same contract as the unconfigured-endpoint paths)
    instead of leaking a raw traceback.
    """
    try:
        return loader()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        detail = str(exc).splitlines()[0].strip() or type(exc).__name__
        err_console.print(f"[red]error:[/red] {action}: {detail}")
        raise typer.Exit(code=2) from exc


def _load_diff_doc(path: str | Path) -> tuple[dict[str, Any], list[SpanDiff]]:
    """Read and validate a ``diff.json`` document produced by ``regatlas diff``."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("diff document must be a JSON object")
    span_diffs = [SpanDiff.model_validate(d) for d in doc.get("span_diffs", [])]
    return doc, span_diffs


def _print_models() -> None:
    table = Table(title="regatlas model endpoints")
    table.add_column("alias", style="cyan", no_wrap=True)
    table.add_column("served model")
    table.add_column("base URL", overflow="fold")
    table.add_column("api key")
    table.add_column("env var")
    table.add_column("status", style="green")
    for ep in list_endpoints():
        env = ""
        for alias in DEFAULT_MODELS:
            if alias == ep.name:
                env = f"REGATLAS_{alias.upper().replace('-', '').replace('.', '')}_*"
                break
        status = "ready" if ep.configured else "no endpoint"
        key_status = "set" if ep.api_key else "unset"
        base = ep.base_url or "(unset)"
        style = "green" if ep.configured else "dim"
        table.add_row(
            ep.name, ep.model, base, key_status, env, status, style=style
        )
    console.print(table)
    console.print(
        "\n[dim]Set REGATLAS_<NAME>_BASE_URL and _API_KEY (e.g. OPUS4) to use a "
        "live endpoint, or replay with --recording for an offline run.[/dim]"
    )


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    list_models: bool = typer.Option(
        False,
        "--list-models",
        help="List configured model endpoints and exit.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the regatlas version and exit.",
    ),
) -> None:
    """regatlas — attribute per-capability regressions after a model swap."""
    if list_models:
        _print_models()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def _resolve_suite(suite: str) -> Path:
    """Resolve a suite path: given path, repo suites/, or bundled suite name."""
    p = Path(suite)
    if p.exists():
        return p
    repo_suite = Path("suites") / f"{suite}.yaml"
    if repo_suite.exists():
        return repo_suite
    repo_suite_named = Path("suites") / suite
    if repo_suite_named.exists():
        return repo_suite_named
    # bundled package data
    try:
        import importlib.resources as resources

        pkg = "regatlas.builtin_suites"
        name = suite if suite.endswith(".yaml") else f"{suite}.yaml"
        name = name.split("/")[-1]
        res = resources.files(pkg).joinpath(name)
        if res.is_file():
            with resources.as_file(res) as extracted:
                return Path(extracted)
    except Exception:  # noqa: BLE001
        pass
    raise typer.BadParameter(
        f"suite not found: {suite!r}. Pass a path, a name in ./suites/, "
        "or a bundled suite name (toolcalling / refusal)."
    )


def _resolve_traj(value: str) -> Path:
    """Resolve a trajectory arg: a file path or a bare model alias."""
    p = Path(value)
    if p.exists():
        return p
    derived = Path(f"traj_{value}.jsonl")
    if derived.exists():
        return derived
    raise typer.BadParameter(
        f"trajectory not found: {value!r}. Pass a JSONL path or a model "
        "alias (resolves to traj_<alias>.jsonl)."
    )


def _write_json(out: Path | None, doc: dict[str, Any]) -> None:
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if out is None or str(out) == "-":
        sys.stdout.write(payload)
    else:
        Path(out).write_text(payload, encoding="utf-8")


@app.command()
def replay(
    suite: str = typer.Option(..., "--suite", help="Suite YAML path or name."),
    model: str = typer.Option(..., "--model", help="Model alias (e.g. opus-4)."),
    recording: Path | None = typer.Option(
        None,
        "--recording",
        help="Offline JSON fixture of recorded responses keyed by task_id.",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Output JSONL path (default: stdout)."
    ),
) -> None:
    """Replay a suite against one model and emit a capability-tagged trajectory."""
    suite_path = _resolve_suite(suite)
    loaded = _load_or_fail(
        f"loading suite {suite_path}", lambda: load_suite(suite_path)
    )
    if recording is not None:
        client: Any = _load_or_fail(
            f"loading recording {recording}",
            lambda: RecordingClient.from_file(recording, model_version=model),
        )
    else:
        endpoint = resolve_endpoint(model)
        if not endpoint.configured:
            err_console.print(
                f"[red]error:[/red] no base URL for model '{model}'. Set "
                f"REGATLAS_{model.upper().replace('-', '').replace('.', '')}_BASE_URL "
                "or pass --recording for an offline run."
            )
            raise typer.Exit(code=2)
        client = ReplayClient(endpoint)
    spans = replay_suite(loaded, client)
    write_trajectory(out, spans)
    err_console.print(
        f"[dim]replayed {len(spans)} task(s) for '{model}' from "
        f"{suite_path}[/dim]"
    )


@app.command()
def run(
    suite: str = typer.Option(..., "--suite", help="Suite YAML path or name."),
    models: str = typer.Option(
        ..., "--models", help="Comma-separated model aliases (e.g. opus-4,opus-5)."
    ),
    recordings: Path | None = typer.Option(
        None,
        "--recordings",
        help="Directory of <alias>.responses.json fixtures for offline replay.",
    ),
    out_dir: Path = typer.Option(
        Path("."), "--out-dir", help="Directory for traj_<alias>.jsonl files."
    ),
) -> None:
    """Replay a suite for multiple models, writing one trajectory per model."""
    suite_path = _resolve_suite(suite)
    loaded = _load_or_fail(
        f"loading suite {suite_path}", lambda: load_suite(suite_path)
    )
    aliases = [m.strip() for m in models.split(",") if m.strip()]
    if not aliases:
        raise typer.BadParameter("no model aliases parsed from --models")
    out_dir.mkdir(parents=True, exist_ok=True)
    for alias in aliases:
        if recordings is not None:
            rec = recordings / f"{alias}.responses.json"
            client: Any = _load_or_fail(
                f"loading recording {rec}",
                lambda: RecordingClient.from_file(rec, model_version=alias),
            )
        else:
            endpoint = resolve_endpoint(alias)
            if not endpoint.configured:
                err_console.print(
                    f"[red]error:[/red] no base URL for model '{alias}'. Set "
                    f"REGATLAS_{alias.upper().replace('-', '').replace('.', '')}_BASE_URL "
                    "or pass --recordings for an offline run."
                )
                raise typer.Exit(code=2)
            client = ReplayClient(endpoint)
        spans = replay_suite(loaded, client)
        dest = out_dir / f"traj_{alias}.jsonl"
        write_trajectory(dest, spans)
        err_console.print(f"wrote {dest} ({len(spans)} spans)")


@app.command()
def diff(
    from_path: str = typer.Option(
        ..., "--from", "--baseline", help="Baseline trajectory (path or alias)."
    ),
    to_path: str = typer.Option(
        ..., "--to", "--candidate", help="Candidate trajectory (path or alias)."
    ),
    suite_name: str | None = typer.Option(
        None, "--suite-name", help="Optional suite label for the diff document."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Output JSON path (default: stdout)."
    ),
) -> None:
    """Align two trajectories and emit signed per-signal span deltas."""
    from_path_resolved = _resolve_traj(from_path)
    to_path_resolved = _resolve_traj(to_path)
    from_spans = _load_or_fail(
        f"reading trajectory {from_path_resolved}",
        lambda: read_trajectory(from_path_resolved),
    )
    to_spans = _load_or_fail(
        f"reading trajectory {to_path_resolved}",
        lambda: read_trajectory(to_path_resolved),
    )
    span_diffs = align_spans(from_spans, to_spans)
    from_model = from_spans[0].model_version if from_spans else None
    to_model = to_spans[0].model_version if to_spans else None
    suite_label = suite_name
    if suite_label is None:
        capabilities = {s.capability for s in [*from_spans, *to_spans]}
        suite_label = ",".join(sorted(capabilities)) or "unknown"
    doc = {
        "from_model": from_model,
        "to_model": to_model,
        "suite": suite_label,
        "span_diffs": [d.model_dump() for d in span_diffs],
    }
    _write_json(out, doc)
    err_console.print(
        f"[dim]aligned {len(span_diffs)} span pair(s): "
        f"{from_model} -> {to_model}[/dim]"
    )


@app.command()
def report(
    diff_file: Path = typer.Option(
        ..., "--diff", help="diff.json document produced by `regatlas diff`."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Output markdown path (default: stdout)."
    ),
) -> None:
    """Aggregate a diff into a per-capability markdown delta map."""
    doc, span_diffs = _load_or_fail(
        f"reading diff document {diff_file}", lambda: _load_diff_doc(diff_file)
    )
    delta_map = aggregate(span_diffs)
    total_tasks = sum(cap.n_tasks for cap in delta_map.values())
    markdown = render_markdown(
        delta_map,
        from_model=doc.get("from_model"),
        to_model=doc.get("to_model"),
        suite_name=doc.get("suite"),
        total_tasks=total_tasks,
    )
    payload = markdown + "\n"
    if out is None or str(out) == "-":
        sys.stdout.write(payload)
    else:
        Path(out).write_text(payload, encoding="utf-8")


EXPORT_FORMATS: tuple[str, ...] = ("langsmith", "langfuse", "json")


@app.command()
def export(
    diff_file: Path = typer.Option(
        ..., "--diff", help="diff.json document produced by `regatlas diff`."
    ),
    fmt: str = typer.Option(
        "langsmith",
        "--format",
        help="Export format: langsmith | langfuse | json.",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Output file path (default: stdout)."
    ),
) -> None:
    """Export a diff to a trace-store adapter (langsmith/langfuse) or standalone JSON."""
    if fmt not in EXPORT_FORMATS:
        raise typer.BadParameter(
            f"unknown format {fmt!r}; expected one of: {', '.join(EXPORT_FORMATS)}"
        )
    _, span_diffs = _load_or_fail(
        f"reading diff document {diff_file}", lambda: _load_diff_doc(diff_file)
    )
    if fmt == "langsmith":
        payload = export_langsmith(span_diffs)
    elif fmt == "langfuse":
        payload = export_langfuse(span_diffs)
    else:
        payload = export_json(span_diffs)
    if out is None or str(out) == "-":
        sys.stdout.write(payload)
    else:
        Path(out).write_text(payload, encoding="utf-8")
    err_console.print(
        f"[dim]exported {len(span_diffs)} span pair(s) as {fmt}[/dim]"
    )
