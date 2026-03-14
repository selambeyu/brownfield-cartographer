from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .agents.archivist import run_archivist
from .agents.semanticist import llm_config_from_env, run_semanticist
from .agents.hydrologist import run_hydrologist, write_lineage_graph_json
from .agents.surveyor import run_surveyor, write_module_graph_json
from .models.evidence import TraceEvent, utc_now_iso, write_trace_event
from .models.graphs import RunConfig


@dataclass(frozen=True)
class RunResult:
    run_id: str
    out_dir: str
    trace_path: str


def run_pipeline(cfg: RunConfig) -> RunResult:
    out_dir = Path(cfg.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid4().hex
    trace_path = str(out_dir / "cartography_trace.jsonl")
    module_graph_path = str(out_dir / "module_graph.json")
    lineage_graph_path = str(out_dir / "lineage_graph.json")

    def emit(event: TraceEvent) -> None:
        write_trace_event(trace_path, event)

    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="run_start", data=cfg.model_dump()))

    # Phase: Surveyor (static structure)
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="surveyor"))
    try:
        survey = run_surveyor(cfg.repo)
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
                    "cycles": len(survey.sccs),
                    "high_velocity_core_files": len(survey.high_velocity_core),
                    "dead_code_candidates": dead_count,
                    "avg_cyclomatic_complexity": avg_cc,
                    "avg_comment_ratio": avg_comment_ratio,
                    "module_graph_path": module_graph_path,
                },
            )
        )
    except Exception as e:
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="error",
                phase="surveyor",
                message=str(e),
            )
        )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="surveyor"))

    # Phase: Hydrologist (data lineage)
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="hydrologist"))
    try:
        lineage_graph, lineage_trace = run_hydrologist(cfg.repo)
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
                data={"lineage_graph_path": lineage_graph_path},
            )
        )
    except Exception as e:
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="error",
                phase="hydrologist",
                message=str(e),
            )
        )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="hydrologist"))

    # Phase: Semanticist (LLM-powered purpose analysis, domain clustering, Day-One scaffold)
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="semanticist"))
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
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="error",
                phase="semanticist",
                message=str(e),
            )
        )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="semanticist"))

    # Phase: Archivist (generate living context artifacts)
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="archivist"))
    try:
        metrics = run_archivist(
            cfg,
            run_id=run_id,
            module_graph_path=module_graph_path,
            lineage_graph_path=lineage_graph_path,
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
        emit(
            TraceEvent(
                ts=utc_now_iso(),
                run_id=run_id,
                event="error",
                phase="archivist",
                message=str(e),
            )
        )
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="archivist"))

    # Phase: Navigator (placeholder until query CLI is implemented)
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_start", phase="navigator"))
    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="phase_end", phase="navigator"))

    emit(TraceEvent(ts=utc_now_iso(), run_id=run_id, event="run_end"))

    return RunResult(run_id=run_id, out_dir=str(out_dir), trace_path=trace_path)

