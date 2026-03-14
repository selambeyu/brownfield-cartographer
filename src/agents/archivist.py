from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models.evidence import utc_now_iso
from ..models.graphs import ArtifactMetadata, RunConfig


def _load_json(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dataset_nodes(lineage: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in lineage.get("nodes", []) if n.get("type") == "dataset"]


def _top_module_hubs(module_graph: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    nodes = {n.get("id"): n for n in module_graph.get("nodes", [])}
    indeg: dict[str, int] = {nid: 0 for nid in nodes}
    for e in module_graph.get("edges", []):
        tgt = e.get("target")
        if tgt in indeg:
            indeg[tgt] += 1
    ranked = sorted(indeg.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"id": nid, "imports_in": score, "path": nodes.get(nid, {}).get("path", nid)} for nid, score in ranked]


def _high_velocity_modules(module_graph: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    mods = [n for n in module_graph.get("nodes", []) if n.get("type") == "module"]
    ranked = sorted(mods, key=lambda n: (n.get("change_velocity_30d") or 0), reverse=True)
    return [
        {"path": m.get("path"), "change_velocity_30d": m.get("change_velocity_30d") or 0}
        for m in ranked[:limit]
    ]


def _module_purpose_map(semantic_modules: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, payload in semantic_modules.items():
        out.append(
            {
                "path": path,
                "purpose_statement": payload.get("purpose_statement"),
                "documentation_drift": payload.get("documentation_drift", "unknown"),
            }
        )
    return sorted(out, key=lambda x: x["path"])


def _lineage_sources_sinks(lineage: dict[str, Any]) -> tuple[list[str], list[str]]:
    datasets = _dataset_nodes(lineage)
    ds_ids = {n.get("id") for n in datasets if n.get("id")}
    incoming: dict[str, int] = {d: 0 for d in ds_ids}
    outgoing: dict[str, int] = {d: 0 for d in ds_ids}
    for e in lineage.get("edges", []):
        src = e.get("source")
        tgt = e.get("target")
        if tgt in incoming:
            incoming[tgt] += 1
        if src in outgoing:
            outgoing[src] += 1
    sources = sorted([d for d, cnt in incoming.items() if cnt == 0])[:20]
    sinks = sorted([d for d, cnt in outgoing.items() if cnt == 0])[:20]
    return sources, sinks


def _render_codebase_md(
    metadata: ArtifactMetadata,
    module_graph: dict[str, Any],
    lineage_graph: dict[str, Any],
    semantic_modules: dict[str, Any],
) -> str:
    hubs = _top_module_hubs(module_graph)
    velocity = _high_velocity_modules(module_graph)
    sources, sinks = _lineage_sources_sinks(lineage_graph)
    purpose_rows = _module_purpose_map(semantic_modules)

    lines: list[str] = []
    lines.append("# CODEBASE.md")
    lines.append("")
    lines.append(f"- artifact_version: `{metadata.artifact_version}`")
    lines.append(f"- run_id: `{metadata.run_id}`")
    lines.append(f"- repo_ref: `{metadata.repo_ref}`")
    lines.append(f"- generated_at: `{metadata.generated_at}`")
    lines.append("")
    lines.append("## Architecture Overview")
    lines.append(
        "This summary is generated from static structure (module graph), data lineage graph, and semantic purpose extraction."
    )
    lines.append("")
    lines.append("## Critical Path (Top Module Hubs)")
    for h in hubs:
        lines.append(f"- `{h['path']}` (imported_by={h['imports_in']})")
    if not hubs:
        lines.append("- No module hubs detected.")
    lines.append("")
    lines.append("## Data Sources and Sinks")
    lines.append("### Sources (in-degree 0)")
    for s in sources:
        lines.append(f"- `{s}`")
    if not sources:
        lines.append("- No lineage sources detected.")
    lines.append("### Sinks (out-degree 0)")
    for s in sinks:
        lines.append(f"- `{s}`")
    if not sinks:
        lines.append("- No lineage sinks detected.")
    lines.append("")
    lines.append("## Known Debt")
    drift = [p for p in purpose_rows if p.get("documentation_drift") == "drift"][:30]
    if drift:
        lines.append("### Documentation Drift Candidates")
        for d in drift:
            lines.append(f"- `{d['path']}`")
    else:
        lines.append("- No documentation drift flags detected.")
    lines.append("")
    lines.append("## Recent Change Velocity")
    for v in velocity:
        lines.append(f"- `{v['path']}` ({v['change_velocity_30d']})")
    if not velocity:
        lines.append("- No velocity data found.")
    lines.append("")
    lines.append("## Module Purpose Index")
    for p in purpose_rows[:200]:
        lines.append(f"- `{p['path']}`: {p.get('purpose_statement') or 'N/A'}")
    if not purpose_rows:
        lines.append("- No semantic purpose statements found.")
    lines.append("")
    lines.append("## Evidence")
    lines.append("- Structural evidence: `.cartography/module_graph.json`")
    lines.append("- Lineage evidence: `.cartography/lineage_graph.json`")
    lines.append("- Semantic evidence: `.cartography/semantic_index/modules.json`")
    return "\n".join(lines) + "\n"


def _render_onboarding_brief_md(
    metadata: ArtifactMetadata,
    module_graph: dict[str, Any],
    lineage_graph: dict[str, Any],
    day_one_answers: dict[str, Any],
) -> str:
    hubs = _top_module_hubs(module_graph, limit=1)
    sources, sinks = _lineage_sources_sinks(lineage_graph)
    top_velocity = _high_velocity_modules(module_graph, limit=5)

    def _todo_or_value(qid: str, fallback: str) -> str:
        payload = day_one_answers.get(qid, {})
        ans = payload.get("answer") if isinstance(payload, dict) else None
        return ans if ans else fallback

    lines: list[str] = []
    lines.append("# onboarding_brief.md")
    lines.append("")
    lines.append(f"- run_id: `{metadata.run_id}`")
    lines.append(f"- repo_ref: `{metadata.repo_ref}`")
    lines.append(f"- generated_at: `{metadata.generated_at}`")
    lines.append("")
    lines.append("## Five FDE Day-One Answers")
    lines.append("")
    lines.append("1) **Primary data ingestion path**")
    lines.append(_todo_or_value("q1_primary_ingestion_path", f"Best-effort sources: {', '.join(sources[:5]) if sources else 'Unknown'}"))
    lines.append("")
    lines.append("2) **3-5 most critical output datasets/endpoints**")
    lines.append(_todo_or_value("q2_critical_outputs", f"Best-effort sinks: {', '.join(sinks[:5]) if sinks else 'Unknown'}"))
    lines.append("")
    lines.append("3) **Blast radius of the most critical module**")
    lines.append(_todo_or_value("q3_blast_radius_critical_module", f"Critical module candidate: {hubs[0]['path'] if hubs else 'Unknown'}"))
    lines.append("")
    lines.append("4) **Where business logic is concentrated vs distributed**")
    lines.append(_todo_or_value("q4_business_logic_distribution", "See CODEBASE critical hubs and module purpose index for concentration signals."))
    lines.append("")
    lines.append("5) **What changed most in the last 90 days**")
    if top_velocity:
        fallback = "High-velocity files: " + ", ".join(v["path"] for v in top_velocity)
    else:
        fallback = "Unknown"
    lines.append(_todo_or_value("q5_recent_change_velocity", fallback))
    lines.append("")
    lines.append("## Evidence")
    lines.append("- `.cartography/module_graph.json` (module graph, velocity, hubs)")
    lines.append("- `.cartography/lineage_graph.json` (sources/sinks, dependency graph)")
    lines.append("- `.cartography/semantic_index/day_one_answers.json` (semantic synthesis when available)")
    return "\n".join(lines) + "\n"


def run_archivist(
    cfg: RunConfig,
    *,
    run_id: str,
    module_graph_path: str,
    lineage_graph_path: str,
    semantic_index_dir: str | None = None,
    changed_paths: list[str] | None = None,
) -> dict[str, Any]:
    out_dir = Path(cfg.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    module_graph = _load_json(module_graph_path)
    lineage_graph = _load_json(lineage_graph_path)

    semantic_modules: dict[str, Any] = {}
    day_one_answers: dict[str, Any] = {}
    if semantic_index_dir:
        semantic_dir = Path(semantic_index_dir)
    else:
        semantic_dir = out_dir / "semantic_index"
    modules_path = semantic_dir / "modules.json"
    day_one_path = semantic_dir / "day_one_answers.json"
    if modules_path.exists():
        semantic_modules = _load_json(str(modules_path))
    if day_one_path.exists():
        day_one_answers = _load_json(str(day_one_path))

    metadata = ArtifactMetadata(
        run_id=run_id,
        repo_ref=cfg.repo,
        generated_at=utc_now_iso(),
    )

    codebase_md = _render_codebase_md(metadata, module_graph, lineage_graph, semantic_modules)
    onboarding_md = _render_onboarding_brief_md(metadata, module_graph, lineage_graph, day_one_answers)

    codebase_path = out_dir / "CODEBASE.md"
    onboarding_path = out_dir / "onboarding_brief.md"

    # Artifact regeneration rules (best-effort):
    # - if no changed paths and both artifacts exist, reuse existing files.
    if changed_paths is not None and len(changed_paths) == 0 and codebase_path.exists() and onboarding_path.exists():
        return {
            "codebase_path": str(codebase_path),
            "onboarding_brief_path": str(onboarding_path),
            "module_count": len(module_graph.get("nodes", [])),
            "lineage_nodes": len(lineage_graph.get("nodes", [])),
            "semantic_modules": len(semantic_modules),
            "reused": True,
            "reuse_reason": "no_changed_files",
        }

    codebase_path.write_text(codebase_md, encoding="utf-8")
    onboarding_path.write_text(onboarding_md, encoding="utf-8")

    return {
        "codebase_path": str(codebase_path),
        "onboarding_brief_path": str(onboarding_path),
        "module_count": len(module_graph.get("nodes", [])),
        "lineage_nodes": len(lineage_graph.get("nodes", [])),
        "semantic_modules": len(semantic_modules),
        "reused": False,
    }

