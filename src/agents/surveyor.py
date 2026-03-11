from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import networkx as nx
import numpy as np
from networkx.readwrite import json_graph

from ..analyzers.tree_sitter_analyzer import LanguageRouter, analyze_module, iter_source_files
from ..models.nodes import ModuleNode


def extract_git_velocity(repo_root: str, path: str, days: int = 90) -> int:
    """
    Change frequency for a file over the last N days.

    Uses git log output; does not execute repository code.
    """
    since = (datetime.now(tz=timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        cp = subprocess.run(
            ["git", "log", f"--since={since}", "--name-only", "--follow", "--", path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return 0

    if cp.returncode != 0:
        return 0

    # Count commits touching this file by counting blank-line-separated commit blocks.
    # This is best-effort and intentionally simple.
    commits = 0
    saw_hash = False
    for line in cp.stdout.splitlines():
        if line.startswith("commit "):
            commits += 1
            saw_hash = True
        elif saw_hash and not line.strip():
            saw_hash = False
    return commits


def _python_module_index(repo_root: str) -> dict[str, str]:
    """
    Map dotted module names to file paths for .py files within repo_root.
    """
    root = Path(repo_root)
    index: dict[str, str] = {}
    for p in root.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__", ".cartography"} for part in p.parts):
            continue
        rel = p.relative_to(root).with_suffix("")
        dotted = ".".join(rel.parts)
        index[dotted] = str(p)
    return index


def _resolve_import_to_path(module_path: str, import_stmt: str, module_index: dict[str, str], repo_root: str) -> str | None:
    """
    Best-effort resolution of Python import statements to repo-internal module file paths.
    """
    # Very small parser: handle "import a.b" and "from a.b import c" and relative "from .x import y".
    import_stmt = import_stmt.strip()
    if import_stmt.startswith("import "):
        target = import_stmt.removeprefix("import ").split(" as ")[0].strip()
        return module_index.get(target)

    if import_stmt.startswith("from "):
        rest = import_stmt.removeprefix("from ").strip()
        mod = rest.split(" import ")[0].strip()
        if mod.startswith("."):
            # relative import: count leading dots and walk up directories
            dots = len(mod) - len(mod.lstrip("."))
            rel_mod = mod.lstrip(".")
            base = Path(module_path).parent
            for _ in range(max(dots - 1, 0)):
                base = base.parent
            if rel_mod:
                rel_path = base / rel_mod.replace(".", "/")
            else:
                rel_path = base
            # try package/__init__.py or module.py
            cand1 = (rel_path / "__init__.py").resolve()
            cand2 = rel_path.with_suffix(".py").resolve()
            root = Path(repo_root).resolve()
            for c in (cand2, cand1):
                try:
                    if root in c.parents and c.exists():
                        return str(c)
                except Exception:
                    continue
            return None
        return module_index.get(mod)

    return None


@dataclass(frozen=True)
class SurveyorResult:
    modules: list[ModuleNode]
    module_graph: nx.DiGraph
    pagerank: dict[str, float]
    sccs: list[list[str]]
    high_velocity_core: list[str]
    dead_code_candidates: dict[str, list[str]]


def run_surveyor(repo_root: str) -> SurveyorResult:
    router = LanguageRouter.create()
    module_index = _python_module_index(repo_root)

    module_nodes: list[ModuleNode] = []
    g = nx.DiGraph()

    files = list(iter_source_files(repo_root))
    py_files = [p for p in files if p.suffix.lower() == ".py"]
    js_files = [p for p in files if p.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}]

    # JS/TS module index for best-effort relative import resolution
    js_index: dict[str, str] = {}
    root = Path(repo_root)
    for p in js_files:
        try:
            js_index[str(p.relative_to(root))] = str(p)
        except Exception:
            js_index[str(p)] = str(p)

    # Compute velocities and core (20% files responsible for 80% changes)
    velocities: dict[str, int] = {}
    for p in py_files:
        rel = str(p.relative_to(Path(repo_root)))
        v = extract_git_velocity(repo_root, rel, days=90)
        velocities[str(p)] = v

    total_changes = sum(velocities.values())
    sorted_files = sorted(velocities.items(), key=lambda kv: kv[1], reverse=True)
    core: list[str] = []
    running = 0
    for i, (fp, v) in enumerate(sorted_files):
        if total_changes <= 0:
            break
        core.append(fp)
        running += v
        # include until we hit 80% or 20% of files, whichever comes first
        if running / total_changes >= 0.80 or (i + 1) / max(len(sorted_files), 1) >= 0.20:
            break

    for p in files:
        m = analyze_module(str(p), router)
        m.change_velocity_30d = velocities.get(str(p), 0)
        module_nodes.append(m)

        # TRP ModuleNode schema + Surveyor extras
        complexity_score = float(m.cyclomatic_complexity) if m.cyclomatic_complexity is not None else None
        g.add_node(
            m.path,
            type="module",
            path=m.path,
            language=m.language,
            purpose_statement=None,
            domain_cluster=None,
            complexity_score=complexity_score,
            change_velocity_30d=m.change_velocity_30d,
            is_dead_code_candidate=False,  # updated after dead-code analysis
            last_modified=None,
            loc=m.loc,
            imports=m.imports,
            public_functions=m.public_functions,
            public_function_signatures=m.public_function_signatures,
            classes=[{"name": c.name, "bases": c.bases} for c in m.classes],
            cyclomatic_complexity=m.cyclomatic_complexity,
            comment_ratio=m.comment_ratio,
            dead_code_candidates=[],
        )

    # IMPORTS edges: source_module → target_module, weight = import_count (TRP schema)
    import_pairs: Counter[tuple[str, str]] = Counter()
    for m in module_nodes:
        for imp in m.imports:
            tgt: str | None = None
            if m.language == "python":
                tgt = _resolve_import_to_path(m.path, imp, module_index, repo_root)
            elif m.language in {"javascript", "typescript"}:
                if " from " in imp:
                    raw = imp.split(" from ", 1)[1].strip().strip(";").strip()
                    if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
                        spec = raw[1:-1]
                        if spec.startswith("."):
                            base = Path(m.path).parent
                            cand = (base / spec).resolve()
                            for ext in (".ts", ".tsx", ".js", ".jsx"):
                                c = cand.with_suffix(ext)
                                if c.exists():
                                    tgt = str(c)
                                    break
                            if tgt is None:
                                for ext in (".ts", ".tsx", ".js", ".jsx"):
                                    c = cand / f"index{ext}"
                                    if c.exists():
                                        tgt = str(c)
                                        break
            if tgt is not None:
                import_pairs[(m.path, tgt)] += 1
    for (src, tgt), weight in import_pairs.items():
        g.add_edge(src, tgt, type="IMPORTS", weight=weight)

    # Dead-code candidates (exported public symbols not referenced elsewhere)
    # Best-effort: we treat any identifier mention in another file as a reference.
    defined_public: dict[str, set[str]] = {}
    used_identifiers: dict[str, set[str]] = {}

    for m in module_nodes:
        if m.language != "python":
            continue
        defined_public[m.path] = set(m.public_functions) | {c.name for c in m.classes}

    def _extract_used_identifiers_py(path: str) -> set[str]:
        from tree_sitter import Node

        p = Path(path)
        parser = router.parser_for("python")
        if parser is None:
            return set()
        src = p.read_bytes()
        tree = parser.parse(src)
        rootn = tree.root_node

        used: set[str] = set()
        stack2: list[Node] = [rootn]
        while stack2:
            n = stack2.pop()
            # identifier nodes include variable names, function calls, attribute names etc.
            # Exclude the identifier that defines a function/class name.
            if n.type == "identifier":
                used.add(src[n.start_byte : n.end_byte].decode("utf-8", errors="replace"))
            stack2.extend(reversed(n.children))
        return used

    for p in py_files:
        used_identifiers[str(p)] = _extract_used_identifiers_py(str(p))

    dead: dict[str, list[str]] = {}
    for mod_path, symbols in defined_public.items():
        refs = set()
        for other_path, used in used_identifiers.items():
            if other_path == mod_path:
                continue
            refs |= (symbols & used)
        dead_syms = sorted(list(symbols - refs))
        if dead_syms:
            dead[mod_path] = dead_syms
        # attach to module node and graph node (TRP: is_dead_code_candidate)
        for m in module_nodes:
            if m.path == mod_path:
                m.dead_code_candidates = dead_syms
                break
        if mod_path in g:
            g.nodes[mod_path]["dead_code_candidates"] = dead_syms
            g.nodes[mod_path]["is_dead_code_candidate"] = len(dead_syms) > 0

    def pagerank_numpy_power_iteration(graph: nx.DiGraph, alpha: float = 0.85, max_iter: int = 100, tol: float = 1.0e-6) -> dict[str, float]:
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            return {}
        idx = {node: i for i, node in enumerate(nodes)}

        out_degree = np.zeros(n, dtype=float)
        for u in nodes:
            out_degree[idx[u]] = float(graph.out_degree(u))

        # Build transition contributions as incoming adjacency lists (sparse by construction)
        incoming: list[list[int]] = [[] for _ in range(n)]
        for u, v in graph.edges():
            incoming[idx[v]].append(idx[u])

        x = np.full(n, 1.0 / n, dtype=float)
        teleport = (1.0 - alpha) / n

        for _ in range(max_iter):
            xlast = x
            x = np.full(n, teleport, dtype=float)

            # dangling nodes distribute uniformly
            dangling_sum = alpha * xlast[out_degree == 0.0].sum() / n
            x += dangling_sum

            for v_i in range(n):
                s = 0.0
                for u_i in incoming[v_i]:
                    if out_degree[u_i] > 0.0:
                        s += xlast[u_i] / out_degree[u_i]
                x[v_i] += alpha * s

            err = np.abs(x - xlast).sum()
            if err < tol:
                break

        # Normalize (numerical stability)
        x = x / x.sum()
        return {nodes[i]: float(x[i]) for i in range(n)}

    pr = pagerank_numpy_power_iteration(g) if g.number_of_nodes() else {}
    sccs = [list(c) for c in nx.strongly_connected_components(g) if len(c) > 1]

    return SurveyorResult(
        modules=module_nodes,
        module_graph=g,
        pagerank=pr,
        sccs=sccs,
        high_velocity_core=core,
        dead_code_candidates=dead,
    )


def write_module_graph_json(graph: nx.DiGraph, out_path: str) -> None:
    # NetworkX node-link JSON serializer (per project requirement)
    data = json_graph.node_link_data(graph, edges="edges")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
