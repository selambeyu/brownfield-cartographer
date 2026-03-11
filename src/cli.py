from __future__ import annotations

from pathlib import Path

import typer

from .models.graphs import RunConfig
from .orchestrator import run_pipeline
from .repo_resolver import resolve_repo

app = typer.Typer(add_completion=False)
analyze_app = typer.Typer(add_completion=False, help="Run analysis pipeline")


def _project_root() -> Path:
    """Project root (directory containing src/)."""
    return Path(__file__).resolve().parents[1]


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()

