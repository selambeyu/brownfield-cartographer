from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .evidence import EvidenceRef


class NodeBase(BaseModel):
    """Base for all knowledge graph nodes. All nodes have an id for graph identity."""

    id: str
    type: str
    evidence: EvidenceRef | None = None


# ---------------------------------------------------------------------------
# Node Types (TRP Knowledge Graph Schema)
# ---------------------------------------------------------------------------


class ModuleNode(NodeBase):
    """
    ModuleNode (per TRP schema):
    path, language, purpose_statement, domain_cluster, complexity_score,
    change_velocity_30d, is_dead_code_candidate, last_modified
    """

    type: Literal["module"] = "module"
    path: str
    language: str
    purpose_statement: str | None = None  # filled by Semanticist
    domain_cluster: str | None = None  # filled by Semanticist
    complexity_score: float | None = None  # e.g. cyclomatic or composite
    change_velocity_30d: int | None = None
    is_dead_code_candidate: bool = False  # True if module has unreferenced exports
    last_modified: str | None = None  # ISO date or commit-ish
    # Extra fields used by Surveyor (derived or for serialization)
    loc: int | None = None
    imports: list[str] = []
    public_functions: list[str] = []
    public_function_signatures: dict[str, str] = {}
    classes: list[ClassDef] = []
    cyclomatic_complexity: int | None = None
    comment_ratio: float | None = None
    dead_code_candidates: list[str] = []  # symbol names


class DatasetNode(NodeBase):
    """
    DatasetNode (per TRP schema):
    name, storage_type [table|file|stream|api], schema_snapshot, freshness_sla,
    owner, is_source_of_truth.
    Used in DataLineageGraph for tables, files, and dynamic/unresolved refs.
    """

    type: Literal["dataset"] = "dataset"
    name: str
    storage_type: Literal["table", "file", "stream", "api"] = "table"
    schema_snapshot: str | None = None
    freshness_sla: str | None = None
    owner: str | None = None
    is_source_of_truth: bool = False
    # Explicit marker for unresolved/dynamic references (e.g. f-strings, variables).
    is_unresolved: bool = False


class FunctionNode(NodeBase):
    """
    FunctionNode (per TRP schema):
    qualified_name, parent_module, signature, purpose_statement,
    call_count_within_repo, is_public_api
    """

    type: Literal["function"] = "function"
    qualified_name: str
    parent_module: str
    signature: str | None = None
    purpose_statement: str | None = None  # filled by Semanticist
    call_count_within_repo: int | None = None
    is_public_api: bool = True


class TransformationNode(NodeBase):
    """
    TransformationNode (per TRP schema):
    source_datasets, target_datasets, transformation_type, source_file,
    line_range, sql_query_if_applicable
    """

    type: Literal["transformation"] = "transformation"
    source_datasets: list[str] = []
    target_datasets: list[str] = []
    transformation_type: str  # e.g. sql, python, notebook
    source_file: str | None = None
    line_range: tuple[int, int] | None = None  # (start, end) 1-based
    sql_query_if_applicable: str | None = None


# Helper for class definitions (used inside ModuleNode; not a top-level graph node type)
class ClassDef(BaseModel):
    name: str
    bases: list[str] = []
    evidence: EvidenceRef | None = None
