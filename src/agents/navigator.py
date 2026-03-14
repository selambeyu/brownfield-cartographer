from __future__ import annotations

import json
import re
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


def _find_implementation_in_module_graph(module_graph_path: str, concept: str, limit: int = 8) -> dict[str, Any]:
    graph = _load_module_graph(module_graph_path)
    q = concept.strip().lower()
    matches: list[dict[str, Any]] = []
    for n in graph.get("nodes", []):
        if n.get("type") != "module":
            continue
        path = str(n.get("path") or "")
        imports = [str(i).lower() for i in n.get("imports", [])]
        funcs = [str(f).lower() for f in n.get("public_functions", [])]
        hay = " ".join([path.lower(), " ".join(imports), " ".join(funcs)])
        if q and q in hay:
            matches.append(
                {
                    "module": path,
                    "public_functions": n.get("public_functions", []),
                    "evidence_method": "semantic_keyword_match",
                }
            )
    return {"concept": concept, "matches": matches[:limit], "evidence_method": "semantic_keyword_match"}


def _find_implementation_in_vector_store(semantic_index_dir: str, concept: str, limit: int = 8) -> dict[str, Any] | None:
    db_path = Path(semantic_index_dir) / "vector_db"
    if not db_path.exists():
        return None
    try:
        import chromadb
    except Exception:
        return None
    try:
        client = chromadb.PersistentClient(path=str(db_path))
        collection = client.get_collection(name="module_purposes")
        result = collection.query(query_texts=[concept], n_results=max(1, limit))
    except Exception:
        return None

    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    matches: list[dict[str, Any]] = []
    for idx, module_id in enumerate(ids):
        metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
        distance = distances[idx] if idx < len(distances) else None
        purpose = documents[idx] if idx < len(documents) else None
        score = None
        if isinstance(distance, (int, float)):
            score = max(0.0, 1.0 - float(distance))
        matches.append(
            {
                "module": metadata.get("path") or module_id,
                "language": metadata.get("language"),
                "documentation_drift": metadata.get("documentation_drift", "unknown"),
                "purpose_statement": purpose,
                "similarity": score,
                "evidence_method": "vector_similarity_chromadb",
            }
        )
    return {
        "concept": concept,
        "matches": matches,
        "vector_store": "chromadb",
        "evidence_method": "vector_similarity_chromadb",
    }


def query_natural_language(
    *,
    question: str,
    out_dir: str = ".cartography",
) -> dict[str, Any]:
    """
    Natural-language query mode with optional LangGraph orchestration.

    Falls back to deterministic rule routing if langgraph is unavailable.
    """
    base = Path(out_dir)
    lineage_path = str(base / "lineage_graph.json")
    module_graph_path = str(base / "module_graph.json")
    semantic_index_dir = str(base / "semantic_index")
    q = question.strip()
    low = q.lower()

    def _route_and_answer(qtext: str) -> dict[str, Any]:
        # trace-lineage intent
        if any(k in low for k in ("upstream", "downstream", "lineage", "depends on", "produces")):
            direction: Literal["upstream", "downstream"] = "downstream" if "downstream" in low else "upstream"
            dataset = qtext
            m = re.search(r"(?:table|dataset)\s+([A-Za-z0-9_\\.:-]+)", qtext, flags=re.IGNORECASE)
            if m:
                dataset = m.group(1)
            return {
                "intent": "trace_lineage",
                "answer": query_trace_lineage(
                    lineage_graph_path=lineage_path,
                    dataset=dataset,
                    direction=direction,
                ),
            }
        # blast radius intent
        if any(k in low for k in ("blast radius", "what breaks", "impact", "affected by")):
            node = qtext
            m = re.search(r"(?:module|dataset|node)\s+([A-Za-z0-9_./:-]+)", qtext, flags=re.IGNORECASE)
            if m:
                node = m.group(1)
            return {
                "intent": "blast_radius",
                "answer": query_blast_radius(lineage_graph_path=lineage_path, node=node),
            }
        # explain module intent
        if any(k in low for k in ("explain", "what does", "describe module")):
            module = qtext
            m = re.search(r"(src/[A-Za-z0-9_./-]+)", qtext)
            if m:
                module = m.group(1)
            return {
                "intent": "explain_module",
                "answer": query_explain_module(
                    module_graph_path=module_graph_path,
                    module_path=module,
                    semantic_index_dir=semantic_index_dir,
                ),
            }
        # find implementation intent (semantic search over module metadata)
        if any(k in low for k in ("where is", "implementation", "logic", "located")):
            concept = qtext
            m = re.search(r"where is (.+)", qtext, flags=re.IGNORECASE)
            if m:
                concept = m.group(1)
            vector_result = _find_implementation_in_vector_store(semantic_index_dir, concept)
            if vector_result is not None and vector_result.get("matches"):
                return {
                    "intent": "find_implementation",
                    "answer": vector_result,
                }
            return {
                "intent": "find_implementation",
                "answer": _find_implementation_in_module_graph(module_graph_path, concept),
            }

        return {
            "intent": "unknown",
            "answer": {
                "error": "Could not route query to a supported tool.",
                "supported_intents": [
                    "trace_lineage",
                    "blast_radius",
                    "explain_module",
                    "find_implementation",
                ],
                "evidence_method": "rule_router",
            },
        }

    # Optional LangGraph orchestration.
    try:
        from langgraph.graph import END, START, StateGraph  # type: ignore

        class _State(dict):
            pass

        def _node_route(state: _State) -> _State:
            routed = _route_and_answer(state["question"])
            state["intent"] = routed["intent"]
            state["answer"] = routed["answer"]
            state["method"] = "langgraph_router"
            return state

        graph = StateGraph(dict)
        graph.add_node("route", _node_route)
        graph.add_edge(START, "route")
        graph.add_edge("route", END)
        app = graph.compile()
        final = app.invoke({"question": q})
        return {
            "question": q,
            "intent": final.get("intent"),
            "result": final.get("answer"),
            "evidence_method": "langgraph_tool_router",
        }
    except Exception:
        routed = _route_and_answer(q)
        return {
            "question": q,
            "intent": routed["intent"],
            "result": routed["answer"],
            "evidence_method": "rule_router",
        }

