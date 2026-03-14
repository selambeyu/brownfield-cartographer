from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunConfig(BaseModel):
    repo: str
    out: str = ".cartography"
    incremental: bool = False
    llm_enabled: bool = False


class ArtifactMetadata(BaseModel):
    artifact_version: str = "0.1"
    run_id: str
    repo_ref: str
    generated_at: str


class GraphArtifact(BaseModel):
    schema_version: str = "0.1"
    graph_type: Literal["module_graph", "lineage_graph", "knowledge_graph"] = "knowledge_graph"
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)

