from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ignore_rules import IgnoreRules
from .agents.archivist import run_archivist
from .agents.hydrologist import run_hydrologist, write_lineage_graph_json
from .agents.semanticist import llm_config_from_env, run_semanticist
from .agents.surveyor import run_surveyor, write_module_graph_json
from .models.evidence import TraceEvent, make_error_envelope, utc_now_iso, write_trace_event
from .models.graphs import RunConfig

ALLOWED_GIT_SUBCOMMANDS = {"rev-parse", "diff"}


@dataclass(frozen=True)
class RunResult:
    run_id: str
    out_dir: str
    trace_path: str


def _stable_run_id(repo_path: str, commit: str | None, started_at: str) -> str:
    """
    Deterministic-yet-unique run id: timestamp + commit + repo hash.
    """
    repo_hash = hashlib.sha1(repo_path.encode("utf-8")).hexdigest()[:8]
    ts = started_at.replace("-", "").replace(":", "").replace("T", "_").replace("+00:00", "Z")
    commit_short = (commit or "nocommit")[:8]
    return f"{ts}_{commit_short}_{repo_hash}"


def _safe_git_run(repo_path: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    if not args or args[0] not in ALLOWED_GIT_SUBCOMMANDS:
        return None
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None


def _git_head(repo_path: str) -> str | None:
    cp = _safe_git_run(repo_path, ["rev-parse", "HEAD"])
    if cp is None:
        return None
    if cp.returncode == 0:
        return cp.stdout.strip() or None
    return None


def _git_changed_files(repo_path: str, from_ref: str, to_ref: str) -> list[str]:
    cp = _safe_git_run(repo_path, ["diff", "--name-only", from_ref, to_ref])
    if cp is None or cp.returncode != 0:
        return []
    return [line.strip() for line in cp.stdout.splitlines() if line.strip()]


def _validate_repo_path(repo_path: str) -> None:
    """
    Enforce read-only analysis constraints at orchestration level.

    The pipeline never executes repository files; it only reads files and runs git metadata
    commands via a small command allowlist.
    """
    p = Path(repo_path)
    if not p.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")
    if not p.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")


def _source_scope_counts(repo_path: str, changed_paths: list[str] | None = None) -> dict[str, int]:
    include_exts = {".py", ".sql", ".yml", ".yaml", ".js", ".jsx", ".ts", ".tsx", ".ipynb"}
    ignore_rules = IgnoreRules.default()
    counts = {
        "files_total": 0,
        "python": 0,
        "sql": 0,
        "yaml": 0,
        "js_ts": 0,
        "notebook": 0,
    }
    root = Path(repo_path).resolve()
    paths: list[Path] = []
    if changed_paths is not None:
        for rel in changed_paths:
            p = (root / rel).resolve()
            if p.exists() and p.is_file():
                try:
                    rel_path = p.relative_to(root)
                except ValueError:
                    continue
                if ignore_rules.should_skip(rel_path):
                    continue
                paths.append(p)
    else:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel_path = p.relative_to(root)
            if ignore_rules.should_skip(rel_path):
                continue
            paths.append(p)

    for p in paths:
        ext = p.suffix.lower()
        if ext not in include_exts:
            continue
        counts["files_total"] += 1
        if ext == ".py":
            counts["python"] += 1
        elif ext == ".sql":
            counts["sql"] += 1
        elif ext in {".yml", ".yaml"}:
            counts["yaml"] += 1
        elif ext in {".ipynb"}:
            counts["notebook"] += 1
        elif ext in {".js", ".jsx", ".ts", ".tsx"}:
            counts["js_ts"] += 1
    return counts


def _load_incremental_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_incremental_state(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_run_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _console_log(message: str) -> None:
    """Emit concise live progress logs to terminal/server stderr."""
    print(f"[cartographer] {message}", file=sys.stderr, flush=True)


def run_pipeline(cfg: RunConfig) -> RunResult:
    run_started_at = utc_now_iso()
    current_commit = _git_head(cfg.repo)
    run_id = _stable_run_id(cfg.repo, current_commit, run_started_at)

    out_dir = Path(cfg.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    trace_path = str(out_dir / "cartography_trace.jsonl")
    module_graph_path = str(out_dir / "module_graph.json")
    lineage_graph_path = str(out_dir / "lineage_graph.json")
    incremental_state_path = out_dir / "incremental_state.json"
    run_metadata_path = out_dir / "run_metadata.json"

    def emit(event: TraceEvent) -> None:
        write_trace_event(trace_path, event)
        data = event.data if isinstance(event.data, dict) else {}

        if event.event == "run_start":
            _console_log(
                "run_start "
                f"run_id={event.run_id} "
                f"incremental={cfg.incremental} "
                f"llm={cfg.llm_enabled} "
                f"repo={cfg.repo}"
            )
        elif event.event == "phase_start" and event.phase:
            _console_log(f"phase_start phase={event.phase}")
        elif event.event == "metric" and event.phase and data.get("reused") is True:
            _console_log(
                "phase_reused "
                f"phase={event.phase} reason={data.get('reason', 'unknown')}"
            )
        elif event.event == "metric" and event.phase and "duration_ms" in data:
            _console_log(
                "phase_end "
                f"phase={event.phase} duration_ms={data['duration_ms']}"
            )
        elif event.event == "error":
            _console_log(
                "error "
                f"phase={event.phase or 'unknown'} "
                f"code={event.error_code or 'unknown'} "
                f"message={event.message or 'n/a'}"
            )
        elif event.event == "run_end":
            _console_log(f"run_end run_id={event.run_id}")

    try:
        _validate_repo_path(cfg.repo)
    except Exception as e:
        env = make_error_envelope(phase="orchestrator", error=e, recoverable=False)
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="error",
                phase="orchestrator",
                message=env.message,
                error_code=env.error_type,
                recoverable=env.recoverable,
                data=env.model_dump(),
            )
        )
        emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="run_end"))
        return RunResult(run_id=run_id, out_dir=str(out_dir), trace_path=trace_path)

    prev_state = _load_incremental_state(incremental_state_path)
    prev_commit = prev_state.get("last_analyzed_commit")
    changed_paths: list[str] = []
    if cfg.incremental and prev_commit and current_commit:
        changed_paths = _git_changed_files(cfg.repo, prev_commit, current_commit)

    can_reuse_all = (
        cfg.incremental
        and prev_commit is not None
        and current_commit is not None
        and len(changed_paths) == 0
        and Path(module_graph_path).exists()
        and Path(lineage_graph_path).exists()
    )
    full_scope = _source_scope_counts(cfg.repo, changed_paths=None)
    changed_scope = _source_scope_counts(cfg.repo, changed_paths=changed_paths) if cfg.incremental else None

    emit(
        TraceEvent(
            ts=utc_now_iso(),
            run_id=run_id,
            event="run_start",
            data={
                **cfg.model_dump(),
                "incremental_state_path": str(incremental_state_path),
                "previous_commit": prev_commit,
                "current_commit": current_commit,
                "changed_paths_count": len(changed_paths),
                "changed_paths_sample": changed_paths[:100],
                "reuse_all_artifacts": can_reuse_all,
                "source_scope_full": full_scope,
                "source_scope_changed": changed_scope,
                "security_policy": {
                    "repository_execution_allowed": False,
                    "allowed_git_subcommands": sorted(ALLOWED_GIT_SUBCOMMANDS),
                },
            },
        )
    )

    # Phase: Surveyor (static structure)
    phase_started = time.perf_counter()
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="surveyor"))
    if can_reuse_all:
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="metric",
                phase="surveyor",
                data={
                    "reused": True,
                    "reason": "no_changed_files",
                    "module_graph_path": module_graph_path,
                },
            )
        )
    else:
        try:
            survey = run_surveyor(cfg.repo, changed_paths=changed_paths if cfg.incremental else None)
            write_module_graph_json(survey.module_graph, module_graph_path)
            dead_count = sum(len(v) for v in survey.dead_code_candidates.values())
            avg_cc = None
            cc_values = [m.cyclomatic_complexity for m in survey.modules if m.cyclomatic_complexity is not None]
            if cc_values:
                avg_cc = sum(cc_values) / len(cc_values)
            avg_comment_ratio = None
            cr_values = [m.comment_ratio for m in survey.modules if m.comment_ratio is not None]
            if cr_values:
                avg_comment_ratio = sum(cr_values) / len(cr_values)
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="metric",
                    phase="surveyor",
                    data={
                        "modules": len(survey.modules),
                        "edges": int(survey.module_graph.number_of_edges()),
                        "files_analyzed": len(survey.modules),
                        "cycles": len(survey.sccs),
                        "high_velocity_core_files": len(survey.high_velocity_core),
                        "dead_code_candidates": dead_count,
                        "avg_cyclomatic_complexity": avg_cc,
                        "avg_comment_ratio": avg_comment_ratio,
                        "module_graph_path": module_graph_path,
                        "recomputed_full": bool(cfg.incremental and len(changed_paths) > 0),
                    },
                )
            )
        except Exception as e:
            env = make_error_envelope(
                phase="surveyor",
                error=e,
                recoverable=True,
                details={"module_graph_path": module_graph_path},
            )
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="error",
                    phase="surveyor",
                    message=env.message,
                    error_code=env.error_type,
                    recoverable=env.recoverable,
                    data=env.model_dump(),
                )
            )
    emit(
        TraceEvent(
            ts=utc_now_iso(),
            run_id=run_id,
            event="metric",
            phase="surveyor",
            data={"duration_ms": int((time.perf_counter() - phase_started) * 1000)},
        )
    )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="surveyor"))

    # Phase: Hydrologist (data lineage)
    phase_started = time.perf_counter()
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="hydrologist"))
    if can_reuse_all:
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="metric",
                phase="hydrologist",
                data={
                    "reused": True,
                    "reason": "no_changed_files",
                    "lineage_graph_path": lineage_graph_path,
                },
            )
        )
    else:
        try:
            lineage_graph, lineage_trace = run_hydrologist(
                cfg.repo,
                changed_paths=changed_paths if cfg.incremental else None,
            )
            write_lineage_graph_json(lineage_graph, lineage_graph_path)
            for ev in lineage_trace:
                emit(
                    TraceEvent(
                        ts=utc_now_iso(),
                        run_id=run_id,
                        event="metric",
                        phase="hydrologist",
                        data=ev,
                    )
                )
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="metric",
                    phase="hydrologist",
                    data={
                        "lineage_graph_path": lineage_graph_path,
                        "recomputed_full": bool(cfg.incremental and len(changed_paths) > 0),
                    },
                )
            )
        except Exception as e:
            env = make_error_envelope(
                phase="hydrologist",
                error=e,
                recoverable=True,
                details={"lineage_graph_path": lineage_graph_path},
            )
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="error",
                    phase="hydrologist",
                    message=env.message,
                    error_code=env.error_type,
                    recoverable=env.recoverable,
                    data=env.model_dump(),
                )
            )
    emit(
        TraceEvent(
            ts=utc_now_iso(),
            run_id=run_id,
            event="metric",
            phase="hydrologist",
            data={"duration_ms": int((time.perf_counter() - phase_started) * 1000)},
        )
    )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="hydrologist"))

    # Phase: Semanticist (LLM-powered purpose analysis, domain clustering, Day-One scaffold)
    phase_started = time.perf_counter()
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="semanticist"))
    if can_reuse_all and (out_dir / "semantic_index").exists():
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="metric",
                phase="semanticist",
                data={
                    "reused": True,
                    "reason": "no_changed_files",
                    "semantic_index_dir": str(out_dir / "semantic_index"),
                },
            )
        )
    else:
        try:
            # When --llm is set, use env-based config (CARTOGRAPHER_LLM_PROVIDER, OLLAMA_*, OPENAI_*, etc.).
            llm_cfg = llm_config_from_env() if cfg.llm_enabled else None
            metrics = run_semanticist(
                cfg,
                module_graph_path=module_graph_path,
                lineage_graph_path=lineage_graph_path,
                llm=llm_cfg,
            )
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="metric",
                    phase="semanticist",
                    data=metrics,
                )
            )
        except Exception as e:
            env = make_error_envelope(phase="semanticist", error=e, recoverable=True)
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="error",
                    phase="semanticist",
                    message=env.message,
                    error_code=env.error_type,
                    recoverable=env.recoverable,
                    data=env.model_dump(),
                )
            )
    emit(
        TraceEvent(
            ts=utc_now_iso(),
            run_id=run_id,
            event="metric",
            phase="semanticist",
            data={"duration_ms": int((time.perf_counter() - phase_started) * 1000)},
        )
    )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="semanticist"))

    # Phase: Archivist (generate living context artifacts)
    phase_started = time.perf_counter()
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="archivist"))
    if can_reuse_all and (out_dir / "CODEBASE.md").exists() and (out_dir / "onboarding_brief.md").exists():
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="metric",
                phase="archivist",
                data={
                    "reused": True,
                    "reason": "no_changed_files",
                    "codebase_path": str(out_dir / "CODEBASE.md"),
                    "onboarding_brief_path": str(out_dir / "onboarding_brief.md"),
                },
            )
        )
    else:
        try:
            metrics = run_archivist(
                cfg,
                run_id=run_id,
                module_graph_path=module_graph_path,
                lineage_graph_path=lineage_graph_path,
                changed_paths=changed_paths if cfg.incremental else None,
            )
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="metric",
                    phase="archivist",
                    data=metrics,
                )
            )
        except Exception as e:
            env = make_error_envelope(phase="archivist", error=e, recoverable=True)
            emit(
                TraceEvent(
                    ts=utc_now_iso(),
                    run_id=run_id,
                    event="error",
                    phase="archivist",
                    message=env.message,
                    error_code=env.error_type,
                    recoverable=env.recoverable,
                    data=env.model_dump(),
                )
            )
    emit(
        TraceEvent(
            ts=utc_now_iso(),
            run_id=run_id,
            event="metric",
            phase="archivist",
            data={"duration_ms": int((time.perf_counter() - phase_started) * 1000)},
        )
    )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="archivist"))

    # Phase: Navigator (placeholder until query CLI is implemented)
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="navigator"))
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="navigator"))

    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="run_end"))

    _write_run_metadata(
        run_metadata_path,
        {
            "run_id": run_id,
            "repo_ref": cfg.repo,
            "commit": current_commit,
            "started_at": run_started_at,
            "completed_at": utc_now_iso(),
            "incremental": cfg.incremental,
            "llm_enabled": cfg.llm_enabled,
            "changed_paths_count": len(changed_paths),
            "changed_paths_sample": changed_paths[:100],
            "reused_all_artifacts": can_reuse_all,
        },
    )

    # Persist incremental state for the next run.
    if current_commit is not None:
        _write_incremental_state(
            incremental_state_path,
            {
                "last_run_id": run_id,
                "last_analyzed_commit": current_commit,
                "last_completed_at": utc_now_iso(),
            },
        )

    return RunResult(run_id=run_id, out_dir=str(out_dir), trace_path=trace_path)

