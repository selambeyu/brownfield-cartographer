from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from ..models.graphs import GraphArtifact


@dataclass
class KnowledgeGraph:
    g: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)
    schema_version: str = "0.1"

    def save(self, path: str) -> None:
        artifact = GraphArtifact(
            schema_version=self.schema_version,
            graph_type="knowledge_graph",
            nodes=[
                {"id": str(node_id), **(attrs or {})}
                for node_id, attrs in self.g.nodes(data=True)
            ],
            edges=[
                {"source": str(u), "target": str(v), **(attrs or {})}
                for u, v, attrs in self.g.edges(data=True)
            ],
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(artifact.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        with open(path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
        artifact = GraphArtifact.model_validate(raw)
        kg = cls(schema_version=artifact.schema_version)
        for n in artifact.nodes:
            node_id = n.get("id")
            attrs = {k: v for k, v in n.items() if k != "id"}
            kg.g.add_node(node_id, **attrs)
        for e in artifact.edges:
            u = e.get("source")
            v = e.get("target")
            attrs = {k: v for k, v in e.items() if k not in ("source", "target")}
            kg.g.add_edge(u, v, **attrs)
        return kg

