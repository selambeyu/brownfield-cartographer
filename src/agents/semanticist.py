from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models.graphs import RunConfig


@dataclass
class ContextWindowBudget:
    """
    Best-effort token budget tracker.

    Rough heuristic: 1 token ≈ 4 characters. This is intentionally simple and
    model-agnostic; callers should set total_budget/max_tokens_per_call based on
    their actual LLM configuration.
    """

    total_budget: int = 200_000
    max_tokens_per_call: int = 3_000
    used_tokens: int = 0

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def can_afford(self, text: str) -> bool:
        est = self.estimate_tokens(text)
        return self.used_tokens + est <= self.total_budget and est <= self.max_tokens_per_call

    def consume_for_text(self, text: str) -> int:
        est = self.estimate_tokens(text)
        self.used_tokens += est
        return est


@dataclass
class LLMConfig:
    """
    Pluggable LLM configuration with optional env-based credentials.

    Supports:
    - ollama: local OLLAMA_BASE_URL + OLLAMA_MODEL_FAST / OLLAMA_MODEL_SLOW
    - openai: OPENAI_API_KEY + optional OPENAI_BASE_URL, OPENAI_MODEL_FAST/SLOW
    - anthropic: ANTHROPIC_API_KEY + ANTHROPIC_MODEL_FAST/SLOW
    """

    provider: str = "none"  # "ollama", "openai", "anthropic"
    cheap_model: str = "gemini-flash"
    expensive_model: str = "gpt-4"
    base_url: Optional[str] = None
    api_key: Optional[str] = None

    def enabled(self) -> bool:
        return self.provider != "none"

    def complete(self, prompt: str, *, fast: bool, max_tokens: int = 512) -> str:
        """Call the configured LLM and return the completion text."""
        model = self.cheap_model if fast else self.expensive_model
        if self.provider == "ollama":
            return _call_ollama(
                base_url=self.base_url or "http://localhost:11434",
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
            )
        if self.provider == "openai":
            return _call_openai(
                base_url=self.base_url,
                api_key=self.api_key or "",
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
            )
        if self.provider == "anthropic":
            return _call_anthropic(
                api_key=self.api_key or "",
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
            )
        raise NotImplementedError(
            f"LLMConfig.complete: provider '{self.provider}' is not implemented."
        )


def _call_ollama(base_url: str, model: str, prompt: str, max_tokens: int) -> str:
    url = base_url.rstrip("/") + "/api/chat"
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama API error: {e.code} {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e
    msg = data.get("message") or {}
    return (msg.get("content") or "").strip()


def _call_openai(
    base_url: Optional[str],
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> str:
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI API error: {e.code} {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"OpenAI request failed: {e}") from e
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content", "").strip()


def _call_anthropic(api_key: str, model: str, prompt: str, max_tokens: int) -> str:
    url = "https://api.anthropic.com/v1/messages"
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Anthropic API error: {e.code} {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"Anthropic request failed: {e}") from e
    content = data.get("content") or []
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "".join(parts).strip()


def llm_config_from_env() -> Optional[LLMConfig]:
    """
    Build an LLMConfig from environment variables. See .env.example for variable names.
    Returns None if provider is unset, "none", or required keys are missing.
    """
    provider = (os.environ.get("CARTOGRAPHER_LLM_PROVIDER") or "").strip().lower()
    if not provider or provider == "none":
        return None

    single_model = (os.environ.get("CARTOGRAPHER_LLM_MODEL") or "").strip()

    if provider == "ollama":
        base_url = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip()
        fast = (os.environ.get("OLLAMA_MODEL_FAST") or "llama3.2").strip()
        slow = (os.environ.get("OLLAMA_MODEL_SLOW") or fast).strip()
        if single_model:
            fast = slow = single_model
        return LLMConfig(
            provider="ollama",
            cheap_model=fast,
            expensive_model=slow,
            base_url=base_url,
        )

    if provider == "openai":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return None
        base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
        fast = (os.environ.get("OPENAI_MODEL_FAST") or "gpt-4o-mini").strip()
        slow = (os.environ.get("OPENAI_MODEL_SLOW") or "gpt-4o").strip()
        if single_model:
            fast = slow = single_model
        return LLMConfig(
            provider="openai",
            cheap_model=fast,
            expensive_model=slow,
            base_url=base_url,
            api_key=api_key,
        )

    if provider == "anthropic":
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            return None
        fast = (os.environ.get("ANTHROPIC_MODEL_FAST") or "claude-3-5-haiku-20241022").strip()
        slow = (os.environ.get("ANTHROPIC_MODEL_SLOW") or "claude-3-5-sonnet-20241022").strip()
        if single_model:
            fast = slow = single_model
        return LLMConfig(
            provider="anthropic",
            cheap_model=fast,
            expensive_model=slow,
            api_key=api_key,
        )

    return None


def _load_module_graph(module_graph_path: str) -> List[Dict[str, Any]]:
    """
    Load NetworkX node-link JSON for the module graph and return module nodes.
    """
    p = Path(module_graph_path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    nodes = data.get("nodes", [])
    return [n for n in nodes if n.get("type") == "module"]


def _load_lineage_graph(lineage_graph_path: str) -> Dict[str, Any]:
    p = Path(lineage_graph_path)
    if not p.exists():
        return {"nodes": [], "edges": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"nodes": [], "edges": []}
    return {
        "nodes": data.get("nodes", []),
        "edges": data.get("edges", []),
    }


def _read_file_or_empty(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_docstring(source: str) -> str:
    """
    Very small heuristic to get the top-level module docstring without importing.
    """
    import ast

    try:
        tree = ast.parse(source)
        doc = ast.get_docstring(tree)
        return doc or ""
    except Exception:
        return ""


def _doc_drift_label(docstring: str, purpose_statement: str) -> str:
    """
    Best-effort documentation drift label.

    - unknown: no docstring or insufficient signal
    - aligned: docstring and inferred purpose share enough semantic tokens
    - drift: low semantic overlap suggests stale/contradictory docs
    """
    if not docstring.strip():
        return "unknown"

    def _tokens(text: str) -> set[str]:
        import re

        toks = re.split(r"[^a-z0-9]+", text.lower())
        stop = {
            "the", "and", "for", "with", "this", "that", "from", "into", "does",
            "module", "function", "class", "data", "code", "file", "is", "are", "to",
        }
        return {t for t in toks if len(t) > 2 and t not in stop}

    d = _tokens(docstring)
    p = _tokens(purpose_statement)
    if not d or not p:
        return "unknown"
    overlap = len(d & p) / max(len(d), 1)
    return "aligned" if overlap >= 0.12 else "drift"


def _heuristic_purpose_from_structure(node: Dict[str, Any]) -> str:
    """
    Fallback deterministic purpose statement when LLMs are disabled/unavailable.
    """
    path = node.get("path", "")
    functions = node.get("public_functions") or []
    classes = [c.get("name") for c in node.get("classes") or []]
    segments = [seg for seg in Path(path).parts if seg not in {"src", "__init__.py"}]
    basename = Path(path).stem

    parts: List[str] = []
    if segments:
        parts.append(f"This module lives under {'/'.join(segments)} and is named '{basename}'.")
    if functions:
        fn_list = ", ".join(functions[:5])
        parts.append(f"It exposes public functions such as {fn_list}.")
    if classes:
        cls_list = ", ".join(classes[:5])
        parts.append(f"It defines classes including {cls_list}.")
    if not parts:
        parts.append("This module is part of the codebase but has limited static signals.")
    parts.append("Purpose is inferred heuristically because LLM analysis is disabled.")
    return " ".join(parts)


def generate_purpose_statement(
    node: Dict[str, Any],
    *,
    cfg: RunConfig,
    budget: ContextWindowBudget,
    llm: Optional[LLMConfig],
) -> Dict[str, Any]:
    """
    Generate a purpose statement for a single module.

    - When `cfg.llm_enabled` and `llm.enabled()` are true and budget allows,
      this should call an LLM with the module's code (not just docstring).
    - Otherwise, falls back to a deterministic, static-analysis-based summary.

    Returns a dict with:
      - purpose_statement: str
      - docstring: str
      - documentation_drift: Literal["unknown", "aligned", "drift"]
    """
    path = node.get("path", "")
    source = _read_file_or_empty(path)
    docstring = _extract_docstring(source) if source else ""

    if not cfg.llm_enabled or llm is None or not llm.enabled():
        purpose = _heuristic_purpose_from_structure(node)
        drift = "unknown"
    else:
        # LLM-powered path (prompt design, but provider wiring left to the user).
        prompt_parts: List[str] = []
        prompt_parts.append(
            "You are a senior engineer reviewing a single module in a larger codebase.\n"
            "Your job is to explain the business purpose of this module, not its line-by-line implementation.\n"
        )
        if docstring:
            prompt_parts.append(
                "Here is the module's existing top-level docstring. If it contradicts the code, "
                "you must call this out explicitly as documentation drift.\n"
                f"--- DOCSTRING START ---\n{docstring}\n--- DOCSTRING END ---\n"
            )
        prompt_parts.append(
            "Here is the full module source code. Ignore comments except when they clarify business rules.\n"
            "Return 2–3 sentences describing:\n"
            "1) What this module is responsible for in the system (business behavior).\n"
            "2) Any important inputs/outputs or external systems it talks to.\n"
            "3) Whether the docstring appears accurate or out-of-date.\n"
            "Do not include implementation details (loops, specific libraries) unless they change the business meaning.\n"
            "--- CODE START ---\n"
        )
        prompt_parts.append(source)
        prompt_parts.append("\n--- CODE END ---\n")
        prompt = "\n".join(prompt_parts)

        if not budget.can_afford(prompt):
            purpose = _heuristic_purpose_from_structure(node)
            drift = _doc_drift_label(docstring, purpose)
        else:
            budget.consume_for_text(prompt)
            try:
                # Use cheap/fast model for bulk per-module summaries.
                completion = llm.complete(prompt, fast=True, max_tokens=256)
                purpose = completion.strip() or _heuristic_purpose_from_structure(node)
            except Exception:
                purpose = _heuristic_purpose_from_structure(node)
            drift = _doc_drift_label(docstring, purpose)

    return {
        "purpose_statement": purpose,
        "docstring": docstring,
        "documentation_drift": drift,
    }


def _tokenize_for_clustering(text: str) -> List[str]:
    import re

    text = text.lower()
    # Split on non-alphanumeric boundaries.
    tokens = re.split(r"[^a-z0-9]+", text)
    return [t for t in tokens if t]


def _build_term_matrix(purposes: Dict[str, str]) -> Tuple[np.ndarray, List[str], List[str]]:
    """
    Very small bag-of-words matrix over purpose statements + path segments.
    Returns (matrix, module_ids, vocabulary).
    """
    vocab_index: Dict[str, int] = {}
    module_ids: List[str] = []
    counts_per_doc: List[Dict[int, float]] = []

    # First pass: build vocabulary and sparse term counts.
    for module_id, text in purposes.items():
        tokens = _tokenize_for_clustering(text)
        if not tokens:
            continue
        counts: Dict[int, float] = {}
        for tok in tokens:
            idx = vocab_index.setdefault(tok, len(vocab_index))
            counts[idx] = counts.get(idx, 0.0) + 1.0
        module_ids.append(module_id)
        counts_per_doc.append(counts)

    if not module_ids:
        return np.zeros((0, 0), dtype=float), [], []

    # Second pass: fixed-width dense rows (prevents ragged numpy arrays).
    vocab_size = len(vocab_index)
    rows: List[List[float]] = []
    for counts in counts_per_doc:
        row = [0.0] * vocab_size
        for idx, cnt in counts.items():
            row[idx] = cnt
        rows.append(row)

    mat = np.array(rows, dtype=float)
    vocab = [None] * vocab_size
    for term, idx in vocab_index.items():
        vocab[idx] = term
    return mat, module_ids, vocab


def _kmeans(mat: np.ndarray, k: int, max_iter: int = 25) -> np.ndarray:
    """
    Very small k-means implementation over rows of `mat`.
    Returns cluster assignment for each row index.
    """
    n_samples = mat.shape[0]
    if n_samples == 0:
        return np.array([], dtype=int)
    k = max(1, min(k, n_samples))
    # Initialize centroids by picking first k rows.
    centroids = mat[:k].copy()
    labels = np.zeros(n_samples, dtype=int)
    for _ in range(max_iter):
        # Assign
        dists = np.linalg.norm(mat[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = np.argmin(dists, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        # Update
        for i in range(k):
            mask = labels == i
            if not np.any(mask):
                continue
            centroids[i] = mat[mask].mean(axis=0)
    return labels


def cluster_into_domains(purposes: Dict[str, str]) -> Dict[str, Any]:
    """
    Cluster modules into inferred business domains using simple k-means over
    bag-of-words vectors derived from their purpose statements and paths.

    Returns a dict:
      - clusters: {cluster_id: {label, modules: [module_path, ...]}}
      - assignments: {module_path: cluster_id}
    """
    mat, module_ids, vocab = _build_term_matrix(purposes)
    if mat.size == 0 or not module_ids:
        return {"clusters": {}, "assignments": {}}

    # Choose small k in [5, 8], capped by number of modules.
    n = len(module_ids)
    k = min(max(5, min(8, n)), n)
    labels = _kmeans(mat, k=k)

    clusters: Dict[int, Dict[str, Any]] = {}
    for idx, module_id in enumerate(module_ids):
        cid = int(labels[idx])
        clusters.setdefault(cid, {"modules": []})
        clusters[cid]["modules"].append(module_id)

    # Label each cluster with top terms in its centroid.
    for cid, payload in clusters.items():
        module_indices = [i for i, mid in enumerate(module_ids) if mid in payload["modules"]]
        if not module_indices:
            payload["label"] = f"domain-{cid}"
            continue
        centroid = mat[module_indices].mean(axis=0)
        top_idx = centroid.argsort()[::-1][:5]
        terms = [vocab[i] for i in top_idx if i < len(vocab)]
        payload["label"] = " / ".join(terms) if terms else f"domain-{cid}"

    assignments = {module_ids[i]: int(labels[i]) for i in range(len(module_ids))}
    return {"clusters": clusters, "assignments": assignments}


def answer_day_one_questions(
    *,
    survey_metrics: Dict[str, Any],
    lineage_metrics: Dict[str, Any],
    llm: Optional[LLMConfig],
    budget: ContextWindowBudget,
) -> Dict[str, Any]:
    """
    Prepare inputs for the Five Day-One FDE Questions and (optionally) delegate
    synthesis to an LLM.

    Questions (from spec):
      1. Primary data ingestion path.
      2. 3–5 most critical output datasets/endpoints.
      3. Blast radius of the most critical module.
      4. Where business logic is concentrated vs. distributed.
      5. What changed most in the last 90 days.

    For now this function prepares a structured payload and, if no LLM is wired,
    returns a skeleton with TODO markers that Archivist can render into
    `.cartography/onboarding_brief.md`.
    """
    answers: Dict[str, Any] = {
        "q1_primary_ingestion_path": {"answer": None, "evidence": [], "status": "todo"},
        "q2_critical_outputs": {"answer": None, "evidence": [], "status": "todo"},
        "q3_blast_radius_critical_module": {"answer": None, "evidence": [], "status": "todo"},
        "q4_business_logic_distribution": {"answer": None, "evidence": [], "status": "todo"},
        "q5_recent_change_velocity": {"answer": None, "evidence": [], "status": "todo"},
    }

    if llm is None or not llm.enabled():
        return answers

    # Provider wiring is intentionally left to the user; we still construct a
    # concise prompt to encourage disciplined token use.
    prompt_obj = {
        "instruction": (
            "You are generating an onboarding brief for a new Foundational Data Engineer (FDE).\n"
            "Using the provided high-level metrics from the Surveyor (module graph) and "
            "Hydrologist (data lineage), answer the Five Day-One questions.\n"
            "Each answer must:\n"
            "- Be 2–4 sentences.\n"
            "- Include specific evidence references (file paths, dataset names, or module ids).\n"
            "- Clearly state when information is inferred vs. directly observed.\n"
        ),
        "survey_metrics": survey_metrics,
        "lineage_metrics": lineage_metrics,
    }
    prompt = json.dumps(prompt_obj, indent=2)
    if not budget.can_afford(prompt):
        return answers
    budget.consume_for_text(prompt)

    try:
        completion = llm.complete(prompt, fast=False, max_tokens=800).strip()
    except Exception:
        return answers

    return {
        "raw_llm_answer": completion,
        "status": "llm_generated",
    }


def _persist_vector_store(semantic_dir: Path, per_module: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Persist module purpose statements in a real vector DB (Chroma).

    The JSON artifacts remain the source of truth for traceability, while this
    collection enables semantic nearest-neighbor queries.
    """
    try:
        import chromadb
    except Exception as e:
        return {"enabled": False, "backend": "chromadb", "error": f"import_failed: {e}"}

    db_path = semantic_dir / "vector_db"
    db_path.mkdir(parents=True, exist_ok=True)
    collection_name = "module_purposes"
    try:
        client = chromadb.PersistentClient(path=str(db_path))
        collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})

        # Replace existing contents for deterministic re-runs.
        existing = collection.get(include=[])
        existing_ids = existing.get("ids") or []
        if existing_ids:
            collection.delete(ids=existing_ids)

        ids: List[str] = []
        docs: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        for module_path, payload in per_module.items():
            purpose = str(payload.get("purpose_statement") or "").strip()
            if not purpose:
                continue
            ids.append(module_path)
            docs.append(purpose)
            metadatas.append(
                {
                    "path": module_path,
                    "language": str(payload.get("language") or "unknown"),
                    "documentation_drift": str(payload.get("documentation_drift") or "unknown"),
                }
            )

        if ids:
            collection.add(ids=ids, documents=docs, metadatas=metadatas)

        return {
            "enabled": True,
            "backend": "chromadb",
            "collection": collection_name,
            "path": str(db_path),
            "indexed_items": len(ids),
        }
    except Exception as e:
        return {"enabled": False, "backend": "chromadb", "path": str(db_path), "error": str(e)}


def _backfill_module_graph_semantics(
    module_graph_path: str,
    per_module: Dict[str, Dict[str, Any]],
    domain_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update module_graph nodes with semantic fields produced by Semanticist.

    This keeps `module_graph.json` aligned with the semantic index so downstream
    tools see purpose/domain directly on module nodes.
    """
    p = Path(module_graph_path)
    if not p.exists():
        return {"updated": False, "reason": "module_graph_missing"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"updated": False, "reason": f"module_graph_read_failed: {e}"}

    nodes = data.get("nodes", [])
    assignments = domain_info.get("assignments", {}) if isinstance(domain_info, dict) else {}
    clusters = domain_info.get("clusters", {}) if isinstance(domain_info, dict) else {}
    updated_count = 0
    for node in nodes:
        if node.get("type") != "module":
            continue
        module_path = node.get("path")
        if not module_path:
            continue
        payload = per_module.get(module_path)
        if not payload:
            continue
        node["purpose_statement"] = payload.get("purpose_statement")
        cluster_id = assignments.get(module_path)
        cluster_payload = {}
        if cluster_id is not None:
            cluster_payload = clusters.get(cluster_id, {}) or clusters.get(str(cluster_id), {})
        cluster_label = cluster_payload.get("label") if isinstance(cluster_payload, dict) else None
        node["domain_cluster"] = str(cluster_label or cluster_id) if cluster_id is not None else None
        updated_count += 1

    data["nodes"] = nodes
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        return {"updated": False, "reason": f"module_graph_write_failed: {e}"}
    return {"updated": True, "modules_backfilled": updated_count}


def run_semanticist(
    cfg: RunConfig,
    module_graph_path: str,
    lineage_graph_path: str,
    *,
    llm: Optional[LLMConfig] = None,
) -> Dict[str, Any]:
    """
    Entry point for Phase 3: Semanticist.

    - Loads the module and lineage graphs.
    - Generates per-module purpose statements (LLM-powered when enabled).
    - Clusters modules into inferred business domains.
    - Prepares a skeleton for the Five Day-One answers (actual brief written by Archivist).

    Returns a small metrics dict suitable for emitting as a trace metric event.
    """
    out_dir = Path(cfg.out)
    semantic_dir = out_dir / "semantic_index"
    semantic_dir.mkdir(parents=True, exist_ok=True)

    modules = _load_module_graph(module_graph_path)
    lineage = _load_lineage_graph(lineage_graph_path)
    budget = ContextWindowBudget()

    if llm is None and cfg.llm_enabled:
        # Prefer env-based config (CARTOGRAPHER_LLM_PROVIDER + provider-specific vars).
        llm = llm_config_from_env()
        if llm is None:
            llm = LLMConfig(provider="none")

    per_module: Dict[str, Dict[str, Any]] = {}
    purposes_for_clustering: Dict[str, str] = {}

    for node in modules:
        module_path = node.get("path")
        if not module_path:
            continue
        res = generate_purpose_statement(node, cfg=cfg, budget=budget, llm=llm)
        per_module[module_path] = {
            "path": module_path,
            "language": node.get("language"),
            "purpose_statement": res["purpose_statement"],
            "docstring": res["docstring"],
            "documentation_drift": res["documentation_drift"],
        }
        purposes_for_clustering[module_path] = f"{module_path} {res['purpose_statement']}"

    domain_info = cluster_into_domains(purposes_for_clustering) if per_module else {"clusters": {}, "assignments": {}}

    module_graph_backfill = _backfill_module_graph_semantics(
        module_graph_path=module_graph_path,
        per_module=per_module,
        domain_info=domain_info,
    )

    # Persist semantic index artifacts.
    modules_path = semantic_dir / "modules.json"
    domains_path = semantic_dir / "domains.json"
    with modules_path.open("w", encoding="utf-8") as f:
        json.dump(per_module, f, indent=2)
    with domains_path.open("w", encoding="utf-8") as f:
        json.dump(domain_info, f, indent=2)

    vector_index = _persist_vector_store(semantic_dir, per_module)

    # Day-One answers are optional and primarily expected to feed Archivist.
    survey_metrics = {
        "module_count": len(modules),
        "top_modules_by_complexity": sorted(
            [
                {"path": m.get("path"), "complexity": m.get("cyclomatic_complexity")}
                for m in modules
                if m.get("cyclomatic_complexity") is not None
            ],
            key=lambda x: x["complexity"],
            reverse=True,
        )[:20],
        "high_velocity_modules": sorted(
            [
                {"path": m.get("path"), "change_velocity_30d": m.get("change_velocity_30d") or 0}
                for m in modules
            ],
            key=lambda x: x["change_velocity_30d"],
            reverse=True,
        )[:20],
    }
    lineage_nodes = lineage.get("nodes", [])
    lineage_edges = lineage.get("edges", [])
    lineage_metrics = {
        "node_count": len(lineage_nodes),
        "edge_count": len(lineage_edges),
        "datasets": [n.get("id") for n in lineage_nodes if n.get("type") == "dataset"][:200],
        "transformations": [n.get("id") for n in lineage_nodes if n.get("type") == "transformation"][:200],
    }

    day_one_answers = answer_day_one_questions(
        survey_metrics=survey_metrics,
        lineage_metrics=lineage_metrics,
        llm=llm if (cfg.llm_enabled and llm and llm.enabled()) else None,
        budget=budget,
    )
    day_one_path = semantic_dir / "day_one_answers.json"
    with day_one_path.open("w", encoding="utf-8") as f:
        json.dump(day_one_answers, f, indent=2)

    return {
        "modules_indexed": len(per_module),
        "domains": len(domain_info.get("clusters", {})),
        "semantic_index_dir": str(semantic_dir),
        "module_graph_backfill": module_graph_backfill,
        "vector_store": vector_index,
        "llm_enabled": cfg.llm_enabled and (llm is not None and llm.enabled()),
        "tokens_used_estimate": budget.used_tokens,
    }

