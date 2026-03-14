from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import networkx as nx


def _load_json(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_lineage_graph(path: str) -> nx.DiGraph:
    raw = _load_json(path)
    g = nx.DiGraph()
    for n in raw.get("nodes", []):
        nid = n.get("id")
        if nid is None:
            continue
        attrs = {k: v for k, v in n.items() if k != "id"}
        g.add_node(nid, **attrs)
    for e in raw.get("edges", []):
        src = e.get("source")
        tgt = e.get("target")
        if src is None or tgt is None:
            continue
        attrs = {k: v for k, v in e.items() if k not in {"source", "target"}}
        g.add_edge(src, tgt, **attrs)
    return g


def _load_module_graph(path: str) -> dict[str, Any]:
    return _load_json(path)


def _normalize_dataset_id(g: nx.DiGraph, dataset: str) -> str | None:
    if dataset in g:
        return dataset
    pref = f"dataset:{dataset}"
    if pref in g:
        return pref
    # fallback by dataset node name
    for nid, data in g.nodes(data=True):
        if data.get("type") == "dataset" and data.get("name") == dataset:
            return str(nid)
    return None


def query_trace_lineage(
    *,
    lineage_graph_path: str,
    dataset: str,
    direction: Literal["upstream", "downstream"] = "upstream",
) -> dict[str, Any]:
    g = _load_lineage_graph(lineage_graph_path)
    ds_id = _normalize_dataset_id(g, dataset)
    if ds_id is None:
        return {
            "dataset": dataset,
            "direction": direction,
            "error": "Dataset not found in lineage graph.",
            "evidence_method": "static_analysis_graph",
        }
    def _is_dataset(nid: str) -> bool:
        return bool(g.nodes.get(nid, {}).get("type") == "dataset")

    def _is_transformation(nid: str) -> bool:
        return bool(g.nodes.get(nid, {}).get("type") == "transformation")

    def _trace_upstream(start: str) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            for pred in g.predecessors(n):
                if _is_transformation(pred):
                    for src in g.predecessors(pred):
                        if _is_dataset(src) and src not in seen:
                            out.append(src)
                            stack.append(src)
                elif _is_dataset(pred) and pred not in seen:
                    out.append(pred)
                    stack.append(pred)
        return out

    def _trace_downstream(start: str) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            for succ in g.successors(n):
                if _is_transformation(succ):
                    for tgt in g.successors(succ):
                        if _is_dataset(tgt) and tgt not in seen:
                            out.append(tgt)
                            stack.append(tgt)
                elif _is_dataset(succ) and succ not in seen:
                    out.append(succ)
                    stack.append(succ)
        return out

    nodes = _trace_upstream(ds_id) if direction == "upstream" else _trace_downstream(ds_id)
    evidence = []
    for n in nodes:
        payload = g.nodes.get(n, {})
        ev = payload.get("evidence")
        if ev:
            evidence.append({"node": n, "evidence": ev})
    return {
        "dataset": ds_id,
        "direction": direction,
        "related_datasets": nodes,
        "evidence": evidence,
        "evidence_method": "static_analysis_graph",
    }


def query_blast_radius(*, lineage_graph_path: str, node: str) -> dict[str, Any]:
    g = _load_lineage_graph(lineage_graph_path)
    node_id = node if node in g else _normalize_dataset_id(g, node)
    if node_id is None:
        return {
            "node": node,
            "error": "Node not found in lineage graph.",
            "evidence_method": "static_analysis_graph",
        }
    def _is_dataset(nid: str) -> bool:
        return bool(g.nodes.get(nid, {}).get("type") == "dataset")

    def _is_transformation(nid: str) -> bool:
        return bool(g.nodes.get(nid, {}).get("type") == "transformation")

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
            if _is_transformation(succ):
                downstream_trans.add(succ)
                data = g.nodes[succ]
                evidence.append(
                    {
                        "node": succ,
                        "source_file": data.get("source_file"),
                        "line_range": data.get("line_range"),
                    }
                )
                stack.append(succ)
            elif _is_dataset(succ):
                downstream_ds.add(succ)
                stack.append(succ)
    result = {
        "downstream_datasets": sorted(downstream_ds),
        "downstream_transformations": sorted(downstream_trans),
        "evidence": evidence,
    }
    result["node"] = node_id
    result["evidence_method"] = "static_analysis_graph"
    return result


def query_explain_module(
    *,
    module_graph_path: str,
    module_path: str,
    semantic_index_dir: str | None = None,
) -> dict[str, Any]:
    mod_graph = _load_module_graph(module_graph_path)
    module_node = None
    for n in mod_graph.get("nodes", []):
        if n.get("type") == "module" and (n.get("path") == module_path or n.get("id") == module_path):
            module_node = n
            break
    if module_node is None:
        return {
            "module": module_path,
            "error": "Module not found in module graph.",
            "evidence_method": "static_analysis_graph",
        }

    semantic_payload = {}
    if semantic_index_dir:
        sem_path = Path(semantic_index_dir) / "modules.json"
    else:
        sem_path = Path(module_graph_path).parent / "semantic_index" / "modules.json"
    if sem_path.exists():
        sem = _load_json(str(sem_path))
        if isinstance(sem, dict):
            semantic_payload = sem.get(module_node.get("path"), {})

    return {
        "module": module_node.get("path"),
        "language": module_node.get("language"),
        "imports": module_node.get("imports", []),
        "public_functions": module_node.get("public_functions", []),
        "classes": module_node.get("classes", []),
        "change_velocity_30d": module_node.get("change_velocity_30d"),
        "purpose_statement": semantic_payload.get("purpose_statement"),
        "documentation_drift": semantic_payload.get("documentation_drift", "unknown"),
        "evidence_method": "static_analysis_graph" if not semantic_payload else "static_plus_llm_semantic",
    }

