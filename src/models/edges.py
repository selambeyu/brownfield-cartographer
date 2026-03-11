from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .evidence import EvidenceRef


class EdgeBase(BaseModel):
    """Base for all knowledge graph edges. source and target are node ids."""

    source: str
    target: str
    type: str
    evidence: EvidenceRef | None = None


# ---------------------------------------------------------------------------
# Edge Types (TRP Knowledge Graph Schema)
# ---------------------------------------------------------------------------

# IMPORTS: source_module → target_module. Weight = import_count.
class ImportsEdge(EdgeBase):
    type: Literal["IMPORTS"] = "IMPORTS"
    weight: int = 1  # import_count


# PRODUCES: transformation → dataset. Captures data lineage (transformation produces dataset).
class ProducesEdge(EdgeBase):
    type: Literal["PRODUCES"] = "PRODUCES"
    transformation_type: str | None = None  # e.g. sql, python, dbt
    source_file: str | None = None
    line_range: tuple[int, int] | None = None  # (start, end) 1-based


# CONSUMES: dataset → transformation. Captures upstream dependencies (transformation consumes dataset).
class ConsumesEdge(EdgeBase):
    type: Literal["CONSUMES"] = "CONSUMES"
    transformation_type: str | None = None
    source_file: str | None = None
    line_range: tuple[int, int] | None = None


# CALLS: function → function. For call graph analysis.
class CallsEdge(EdgeBase):
    type: Literal["CALLS"] = "CALLS"


# CONFIGURES: config_file → module/pipeline. YAML/ENV relationship.
class ConfiguresEdge(EdgeBase):
    type: Literal["CONFIGURES"] = "CONFIGURES"
