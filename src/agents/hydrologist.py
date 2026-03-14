"""
Hydrologist agent: data lineage and blast radius.

Builds the DataLineageGraph (NetworkX DiGraph) from SQL, dbt/YAML config, and Python
data-flow analysis. Supports trace_upstream, trace_downstream, find_sources, find_sinks,
and blast_radius. Unresolved/dynamic references are represented explicitly in the graph
and trace (no silent omission).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import networkx as nx

from ..analyzers.airflow_dag_parser import AirflowDAGResult, extract_airflow_dag_from_file
from ..analyzers.dag_config_parser import DAGConfigResult, extract_dag_config
from ..analyzers.sql_lineage import (
    SQLLineageResult,
    extract_sql_lineage_from_file,
    extract_tables_from_sql_string,
)
from ..analyzers.tree_sitter_analyzer import (
    LanguageRouter,
    extract_python_data_flow,
    iter_source_files,
)
from ..models.evidence import EvidenceRef

# Node id prefixes for lineage graph
DATASET_PREFIX = "dataset:"
TRANSFORMATION_PREFIX = "transformation:"
AIRFLOW_TASK_PREFIX = "airflow_task:"
UNRESOLVED_PREFIX = "dataset:__unresolved__"


def _dataset_id(name: str, unresolved: bool = False, evidence_key: str | None = None) -> str:
    if unresolved or not name:
        key = evidence_key or str(id(name))
        return f"{UNRESOLVED_PREFIX}{key}"
    return f"{DATASET_PREFIX}{name}"


def _transformation_id(source_file: str, line_start: int) -> str:
    return f"{TRANSFORMATION_PREFIX}{source_file}:{line_start}"


def _ensure_dataset_node(
    g: nx.DiGraph,
    name: str,
    storage_type: str = "table",
    unresolved: bool = False,
    evidence: EvidenceRef | None = None,
    evidence_key: str | None = None,
) -> str:
    if unresolved and evidence_key:
        nid = _dataset_id("", unresolved=True, evidence_key=evidence_key)
    else:
        nid = _dataset_id(name or "dynamic", unresolved=unresolved)
    if not g.has_node(nid):
        payload: dict[str, Any] = {
            "type": "dataset",
            "name": name or "dynamic reference (unresolved)",
            "storage_type": storage_type,
            "is_unresolved": unresolved,
        }
        if evidence:
            payload["evidence"] = evidence.model_dump() if hasattr(evidence, "model_dump") else {"path": evidence.path, "line_start": evidence.line_start, "line_end": evidence.line_end}
        g.add_node(nid, **payload)
    return nid


def _ensure_transformation_node(
    g: nx.DiGraph,
    source_file: str,
    line_start: int,
    line_end: int | None,
    transformation_type: str,
    evidence: EvidenceRef | None = None,
) -> str:
    nid = _transformation_id(source_file, line_start)
    if not g.has_node(nid):
        payload: dict[str, Any] = {
            "type": "transformation",
            "transformation_type": transformation_type,
            "source_file": source_file,
            "line_range": (line_start, line_end or line_start),
            "source_datasets": [],
            "target_datasets": [],
        }
        if evidence:
            payload["evidence"] = evidence.model_dump() if hasattr(evidence, "model_dump") else {"path": evidence.path, "line_start": evidence.line_start, "line_end": evidence.line_end}
        g.add_node(nid, **payload)
    return nid


def _add_consumes(g: nx.DiGraph, dataset_id: str, transformation_id: str, edge_attrs: dict[str, Any]) -> None:
    if not g.has_edge(dataset_id, transformation_id):
        g.add_edge(dataset_id, transformation_id, type="CONSUMES", **edge_attrs)


def _add_produces(g: nx.DiGraph, transformation_id: str, dataset_id: str, edge_attrs: dict[str, Any]) -> None:
    if not g.has_edge(transformation_id, dataset_id):
        g.add_edge(transformation_id, dataset_id, type="PRODUCES", **edge_attrs)


def _airflow_task_id(path: str, task_id: str, dag_id: str | None = None) -> str:
    return f"{AIRFLOW_TASK_PREFIX}{path}:{dag_id or 'default'}:{task_id}"


def _ensure_airflow_task_node(
    g: nx.DiGraph,
    path: str,
    task_id: str,
    dag_id: str | None,
    operator: str,
    line: int,
    evidence: EvidenceRef | None = None,
) -> str:
    nid = _airflow_task_id(path, task_id, dag_id)
    if not g.has_node(nid):
        payload: dict[str, Any] = {
            "type": "transformation",
            "transformation_type": "airflow",
            "task_id": task_id,
            "dag_id": dag_id or "default",
            "operator": operator,
            "source_file": path,
            "line_range": (line, line),
        }
        if evidence:
            payload["evidence"] = evidence.model_dump() if hasattr(evidence, "model_dump") else {"path": evidence.path, "line_start": evidence.line_start, "line_end": evidence.line_end}
        g.add_node(nid, **payload)
    return nid


def _add_triggers(g: nx.DiGraph, upstream_id: str, downstream_id: str, edge_attrs: dict[str, Any]) -> None:
    if not g.has_edge(upstream_id, downstream_id):
        g.add_edge(upstream_id, downstream_id, type="TRIGGERS", **edge_attrs)


def _extract_notebook_data_flow(path: Path) -> list[tuple[str | None, str, EvidenceRef]]:
    """
    Parse .ipynb code cells for basic data IO patterns.

    Returns tuples of (dataset_name_or_none, kind["read"|"write"], evidence).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    cells = raw.get("cells")
    if not isinstance(cells, list):
        return []

    items: list[tuple[str | None, str, EvidenceRef]] = []
    # pandas/PySpark-like IO patterns plus SQL strings.
    io_pattern = re.compile(
        r"""(?ix)
        (?:
            \bread_(?:csv|parquet|sql|table)\s*\(\s*["']([^"']+)["'] |
            \bto_(?:csv|parquet|sql)\s*\(\s*["']([^"']+)["'] |
            \bsaveAsTable\s*\(\s*["']([^"']+)["'] |
            \btable\s*\(\s*["']([^"']+)["']
        )
        """
    )
    # execute("select ...") / spark.sql("...")
    sql_call_pattern = re.compile(r"""(?is)\b(?:execute|sql)\s*\(\s*["'](select|with|insert|create).*?["']\s*\)""")

    for i, cell in enumerate(cells):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        src = cell.get("source")
        if isinstance(src, list):
            code = "".join(str(x) for x in src)
        else:
            code = str(src or "")
        ev = EvidenceRef(path=str(path), line_start=i + 1, line_end=i + 1)

        for m in io_pattern.finditer(code):
            dataset = next((g for g in m.groups() if g), None)
            if dataset is None:
                continue
            snippet = m.group(0).lower()
            kind = "read"
            if any(x in snippet for x in ("to_csv", "to_parquet", "to_sql", "saveastable")):
                kind = "write"
            items.append((dataset, kind, ev))

        for sql_match in re.finditer(r"""(?is)\b(?:execute|sql)\s*\(\s*["'](.+?)["']\s*\)""", code):
            sql_str = sql_match.group(1)
            src_tables, tgt_table = extract_tables_from_sql_string(sql_str)
            for t in src_tables:
                items.append((t, "read", ev))
            if tgt_table:
                items.append((tgt_table, "write", ev))

    return items


def run_hydrologist(repo_root: str) -> tuple[nx.DiGraph, list[dict[str, Any]]]:
    """
    Build the lineage DAG from SQL, YAML config, and Python files in the repo.

    Returns (lineage_graph, trace_events). Trace events include parse errors,
    unresolved refs, and coverage metrics. Unresolved references are added as
    dataset nodes with is_unresolved=True.
    """
    g: nx.DiGraph = nx.DiGraph()
    trace_events: list[dict[str, Any]] = []
    router = LanguageRouter.create()
    files_sql = 0
    files_yaml = 0
    files_python = 0
    unresolved_count = 0

    root = Path(repo_root)
    for path in iter_source_files(repo_root):
        p = Path(path)
        if p.suffix.lower() == ".sql":
            files_sql += 1
            res = extract_sql_lineage_from_file(p)
            if res.parse_error:
                trace_events.append({"event": "sql_parse_error", "path": res.path, "message": res.parse_error})
                continue
            evidence = res.evidence
            line_start = evidence.line_start or 1
            line_end = evidence.line_end or 1
            trans_id = _ensure_transformation_node(
                g, res.path, line_start, line_end, "sql", evidence=evidence
            )
            # Target: explicit (INSERT/CREATE) or derive from path (e.g. dbt model name)
            target_name = res.target_table
            if not target_name and res.path:
                # dbt: model name often equals filename without extension
                target_name = p.stem
            if target_name:
                ds_id = _ensure_dataset_node(g, target_name, "table", unresolved=False, evidence=evidence)
                _add_produces(g, trans_id, ds_id, {"transformation_type": "sql", "source_file": res.path, "line_range": (line_start, line_end)})
            for src in res.source_tables:
                src_id = _ensure_dataset_node(g, src, "table")
                _add_consumes(g, src_id, trans_id, {"transformation_type": "sql", "source_file": res.path, "line_range": (line_start, line_end)})

        elif p.suffix.lower() in (".yml", ".yaml"):
            files_yaml += 1
            cfg = extract_dag_config(p)
            if cfg.parse_error:
                trace_events.append({"event": "yaml_parse_error", "path": cfg.path, "message": cfg.parse_error})
                continue
            for model_name in cfg.models:
                _ensure_dataset_node(g, model_name, "table", evidence=cfg.evidence)
            for src_name in cfg.sources:
                _ensure_dataset_node(g, src_name, "table", evidence=cfg.evidence)
            for src_tbl in cfg.source_tables:
                _ensure_dataset_node(g, src_tbl, "table", evidence=cfg.evidence)
            # If YAML contains explicit depends_on refs, wire config-derived topology.
            for model_name, deps in cfg.model_dependencies.items():
                trans_id = _ensure_transformation_node(
                    g,
                    cfg.path,
                    cfg.evidence.line_start or 1,
                    cfg.evidence.line_end,
                    "dbt_config",
                    evidence=cfg.evidence,
                )
                model_id = _ensure_dataset_node(g, model_name, "table", evidence=cfg.evidence)
                _add_produces(
                    g,
                    trans_id,
                    model_id,
                    {"transformation_type": "dbt_config", "source_file": cfg.path, "line_range": (cfg.evidence.line_start or 1, cfg.evidence.line_end or (cfg.evidence.line_start or 1))},
                )
                for dep in deps:
                    dep_id = _ensure_dataset_node(g, dep, "table", evidence=cfg.evidence)
                    _add_consumes(
                        g,
                        dep_id,
                        trans_id,
                        {"transformation_type": "dbt_config", "source_file": cfg.path, "line_range": (cfg.evidence.line_start or 1, cfg.evidence.line_end or (cfg.evidence.line_start or 1))},
                    )

        elif p.suffix.lower() == ".py":
            files_python += 1
            try:
                source_bytes = p.read_bytes()
            except Exception as e:
                trace_events.append({"event": "read_error", "path": str(p), "message": str(e)})
                continue
            # Airflow DAG parsing (pipeline topology from config/code)
            airflow_res = extract_airflow_dag_from_file(p)
            if airflow_res.tasks or airflow_res.dependencies:
                if airflow_res.parse_error:
                    trace_events.append({"event": "airflow_parse_error", "path": airflow_res.path, "message": airflow_res.parse_error})
                else:
                    task_ids = {t["task_id"] for t in airflow_res.tasks}
                    for task in airflow_res.tasks:
                        _ensure_airflow_task_node(
                            g, str(p), task["task_id"], airflow_res.dag_id,
                            task["operator"], task["line"], airflow_res.evidence,
                        )
                    for u, d in airflow_res.dependencies:
                        u_id = _airflow_task_id(str(p), u, airflow_res.dag_id)
                        d_id = _airflow_task_id(str(p), d, airflow_res.dag_id)
                        if g.has_node(u_id) and g.has_node(d_id):
                            _add_triggers(g, u_id, d_id, {"source_file": str(p), "transformation_type": "airflow"})
            items = extract_python_data_flow(str(p), source_bytes, router)
            for name, kind, ev in items:
                line_start = ev.line_start or 1
                line_end = ev.line_end or line_start
                trans_id = _ensure_transformation_node(g, str(p), line_start, line_end, "python", evidence=ev)
                unresolved = name is None or name == ""
                if unresolved:
                    name = "dynamic reference, cannot resolve"
                    unresolved_count += 1
                ev_key = f"{ev.path}:{ev.line_start or 0}:{ev.line_end or 0}" if ev else None
                ds_id = _ensure_dataset_node(
                    g, name, "file" if kind == "read" else "table",
                    unresolved=unresolved, evidence=ev, evidence_key=ev_key if unresolved else None,
                )
                if kind == "read":
                    _add_consumes(g, ds_id, trans_id, {"transformation_type": "python", "source_file": str(p), "line_range": (line_start, line_end)})
                else:
                    _add_produces(g, trans_id, ds_id, {"transformation_type": "python", "source_file": str(p), "line_range": (line_start, line_end)})

        elif p.suffix.lower() == ".ipynb":
            # Notebook support for mixed DS/DE pipelines.
            for name, kind, ev in _extract_notebook_data_flow(p):
                line_start = ev.line_start or 1
                line_end = ev.line_end or line_start
                trans_id = _ensure_transformation_node(g, str(p), line_start, line_end, "notebook", evidence=ev)
                unresolved = name is None or name == ""
                if unresolved:
                    name = "dynamic reference, cannot resolve"
                    unresolved_count += 1
                ev_key = f"{ev.path}:{ev.line_start or 0}:{ev.line_end or 0}"
                ds_id = _ensure_dataset_node(
                    g,
                    name,
                    "file" if kind == "read" else "table",
                    unresolved=unresolved,
                    evidence=ev,
                    evidence_key=ev_key if unresolved else None,
                )
                if kind == "read":
                    _add_consumes(
                        g, ds_id, trans_id,
                        {"transformation_type": "notebook", "source_file": str(p), "line_range": (line_start, line_end)},
                    )
                else:
                    _add_produces(
                        g, trans_id, ds_id,
                        {"transformation_type": "notebook", "source_file": str(p), "line_range": (line_start, line_end)},
                    )

    trace_events.append({
        "event": "lineage_coverage",
        "files_sql": files_sql,
        "files_yaml": files_yaml,
        "files_python": files_python,
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "unresolved_refs": unresolved_count,
    })
    return g, trace_events


def _is_dataset_node(g: nx.DiGraph, n: str) -> bool:
    return (g.nodes[n].get("type") == "dataset") if g.has_node(n) else False


def _is_transformation_node(g: nx.DiGraph, n: str) -> bool:
    return (g.nodes[n].get("type") == "transformation") if g.has_node(n) else False


def trace_upstream(g: nx.DiGraph, dataset_id: str) -> list[str]:
    """
    Return all upstream dataset node ids (datasets that feed into this one).
    Traverses backward: dataset <- PRODUCES <- transformation <- CONSUMES <- source datasets.
    """
    if not g.has_node(dataset_id):
        return []
    seen: set[str] = set()
    result: list[str] = []
    stack = [dataset_id]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for pred in g.predecessors(n):
            if _is_transformation_node(g, pred):
                for src in g.predecessors(pred):
                    if _is_dataset_node(g, src) and src not in seen:
                        result.append(src)
                        stack.append(src)
            elif _is_dataset_node(g, pred) and pred not in seen:
                result.append(pred)
                stack.append(pred)
    return result


def trace_downstream(g: nx.DiGraph, dataset_id: str) -> list[str]:
    """
    Return all downstream dataset node ids (datasets that depend on this one).
    Traverses forward: dataset -> CONSUMES -> transformation -> PRODUCES -> target datasets.
    """
    if not g.has_node(dataset_id):
        return []
    seen: set[str] = set()
    result: list[str] = []
    stack = [dataset_id]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for succ in g.successors(n):
            if _is_transformation_node(g, succ):
                for tgt in g.successors(succ):
                    if _is_dataset_node(g, tgt) and tgt not in seen:
                        result.append(tgt)
                        stack.append(tgt)
            elif _is_dataset_node(g, succ) and succ not in seen:
                result.append(succ)
                stack.append(succ)
    return result


def find_sources(g: nx.DiGraph) -> list[str]:
    """Nodes with in-degree 0 (entry points: no transformation produces them in this graph)."""
    return [n for n in g.nodes() if _is_dataset_node(g, n) and g.in_degree(n) == 0]


def find_sinks(g: nx.DiGraph) -> list[str]:
    """Nodes with out-degree 0 (exit points: no transformation consumes them)."""
    return [n for n in g.nodes() if _is_dataset_node(g, n) and g.out_degree(n) == 0]


def blast_radius(g: nx.DiGraph, node_id: str) -> dict[str, Any]:
    """
    BFS/DFS from a node to find all downstream dependents (blast radius).
    Returns dict with 'downstream_datasets', 'downstream_transformations', and 'evidence' hints.
    """
    if not g.has_node(node_id):
        return {"downstream_datasets": [], "downstream_transformations": [], "evidence": []}
    downstream_ds: set[str] = set()
    downstream_trans: set[str] = set()
    evidence: list[dict[str, Any]] = []
    stack = [node_id]
    visited = set()
    while stack:
        n = stack.pop()
        if n in visited:
            continue
        visited.add(n)
        for succ in g.successors(n):
            if succ in visited:
                continue
            if _is_transformation_node(g, succ):
                downstream_trans.add(succ)
                data = g.nodes[succ]
                evidence.append({
                    "node": succ,
                    "source_file": data.get("source_file"),
                    "line_range": data.get("line_range"),
                })
                stack.append(succ)
            elif _is_dataset_node(g, succ):
                downstream_ds.add(succ)
                stack.append(succ)
    return {
        "downstream_datasets": sorted(downstream_ds),
        "downstream_transformations": sorted(downstream_trans),
        "evidence": evidence,
    }


def lineage_graph_to_artifact(g: nx.DiGraph, schema_version: str = "0.1") -> dict[str, Any]:
    """Serialize lineage graph to the same format as KnowledgeGraph (nodes + edges)."""
    nodes = []
    for nid, data in g.nodes(data=True):
        nodes.append({"id": nid, **data})
    edges = []
    for u, v, data in g.edges(data=True):
        edges.append({"source": u, "target": v, **data})
    return {
        "schema_version": schema_version,
        "graph_type": "lineage_graph",
        "nodes": nodes,
        "edges": edges,
    }


def write_lineage_graph_json(g: nx.DiGraph, path: str) -> None:
    """Write lineage graph to JSON file (same layout as module_graph)."""
    import json
    artifact = lineage_graph_to_artifact(g)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
