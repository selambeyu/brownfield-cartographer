from __future__ import annotations

import json
from pathlib import Path

import typer
from dotenv import load_dotenv

from .agents.navigator import query_blast_radius, query_explain_module, query_trace_lineage
from .models.graphs import RunConfig

load_dotenv()
from .orchestrator import run_pipeline
from .repo_resolver import resolve_repo

app = typer.Typer(add_completion=False)
analyze_app = typer.Typer(add_completion=False, help="Run analysis pipeline")
query_app = typer.Typer(add_completion=False, help="Query persisted cartography artifacts")


def _project_root() -> Path:
    """Project root (directory containing src/)."""
    return Path(__file__).resolve().parents[1]


def _echo_json(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@analyze_app.command("run")
def run(
    repo: str = typer.Option(..., "--repo", help="Local path or GitHub URL"),
    out: str = typer.Option(".cartography", "--out", help="Output directory for artifacts"),
    incremental: bool = typer.Option(False, "--incremental", help="Best-effort incremental mode"),
    llm_enabled: bool = typer.Option(False, "--llm", help="Enable LLM-powered semantic analysis"),
    keep_clone: bool = typer.Option(False, "--keep-clone", help="If repo is a URL, keep the cloned temp dir"),
) -> None:
    """
    Run the Cartographer analysis pipeline.

    Phase 2: emits trace + phase boundaries. Later phases add real analysis.
    Output is always under the project directory so URL and local runs write to the same place.
    """
    # Resolve relative --out to project root so URL and local runs write to the same .cartography/
    out_path = Path(out)
    if not out_path.is_absolute():
        out = str((_project_root() / out).resolve())

    with resolve_repo(repo, keep_clone=keep_clone) as (resolved_path, cleanup_path):
        cfg = RunConfig(repo=resolved_path, out=out, incremental=incremental, llm_enabled=llm_enabled)
        result = run_pipeline(cfg)
        typer.echo(f"run_id={result.run_id}")
        typer.echo(f"out_dir={result.out_dir}")
        typer.echo(f"trace={result.trace_path}")
        if cleanup_path is not None:
            typer.echo(f"cloned_repo={cleanup_path}")

app.add_typer(analyze_app, name="analyze")
app.add_typer(query_app, name="query")


@query_app.command("trace-lineage")
def trace_lineage(
    dataset: str = typer.Option(..., "--dataset", help="Dataset id or name"),
    direction: str = typer.Option("upstream", "--direction", help="upstream|downstream"),
    out: str = typer.Option(".cartography", "--out", help="Artifact output directory"),
) -> None:
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = (_project_root() / out).resolve()
    lineage_path = str(out_path / "lineage_graph.json")
    result = query_trace_lineage(
        lineage_graph_path=lineage_path,
        dataset=dataset,
        direction="downstream" if direction.lower() == "downstream" else "upstream",
    )
    _echo_json(result)


@query_app.command("blast-radius")
def blast_radius_cmd(
    node: str = typer.Option(..., "--node", help="Dataset/transformation node id or dataset name"),
    out: str = typer.Option(".cartography", "--out", help="Artifact output directory"),
) -> None:
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = (_project_root() / out).resolve()
    lineage_path = str(out_path / "lineage_graph.json")
    result = query_blast_radius(lineage_graph_path=lineage_path, node=node)
    _echo_json(result)


@query_app.command("explain-module")
def explain_module(
    path: str = typer.Option(..., "--path", help="Module path"),
    out: str = typer.Option(".cartography", "--out", help="Artifact output directory"),
) -> None:
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = (_project_root() / out).resolve()
    module_graph_path = str(out_path / "module_graph.json")
    semantic_index_dir = str(out_path / "semantic_index")
    result = query_explain_module(
        module_graph_path=module_graph_path,
        module_path=path,
        semantic_index_dir=semantic_index_dir,
    )
    _echo_json(result)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

