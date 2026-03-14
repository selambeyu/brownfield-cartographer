"""
DAG config parser: extract pipeline topology from dbt schema.yml.

Parses dbt schema.yml (and related .yml in models/) to extract model names, sources,
and config file → model associations. Does not extract ref() dependencies (those
come from SQL lineage); this layer provides model/source inventory.

For Airflow DAG Python files, use airflow_dag_parser.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..models.evidence import EvidenceRef


@dataclass
class DAGConfigResult:
    """Result of parsing one config file for pipeline topology."""

    path: str
    evidence: EvidenceRef
    # Model names declared in this file (dbt: models[*].name).
    models: list[str] = field(default_factory=list)
    # Source names (dbt: sources[*].name).
    sources: list[str] = field(default_factory=list)
    # Fully-qualified dbt sources from schema.yml: source_name.table_name.
    source_tables: list[str] = field(default_factory=list)
    # dbt model dependency hints from YAML (depends_on / refs).
    model_dependencies: dict[str, list[str]] = field(default_factory=dict)
    # Raw keys found at top level (e.g. "models", "sources", "version").
    parse_error: str | None = None


def _safe_line_range(path: str, num_lines: int = 1) -> EvidenceRef:
    """Best-effort line range for a YAML file (we don't have line numbers from PyYAML by default)."""
    return EvidenceRef(path=path, line_start=1, line_end=max(1, num_lines))


def extract_dag_config(file_path: str | Path) -> DAGConfigResult:
    """
    Extract model/source names from a dbt schema.yml or similar YAML config.

    Supports:
    - dbt: top-level "models" (list of {name: ...}) and "sources" (list of {name: ...}).
    - Other YAML with "models" or "sources" keys are parsed best-effort.

    Args:
        file_path: Path to the YAML file.

    Returns:
        DAGConfigResult with models, sources, and evidence.
    """
    path = Path(file_path)
    evidence = EvidenceRef(path=str(path))
    if not path.exists():
        return DAGConfigResult(path=str(path), evidence=evidence, parse_error="File not found")

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        num_lines = len(raw.splitlines()) or 1
        evidence = _safe_line_range(str(path), num_lines)
        data = yaml.safe_load(raw)
    except Exception as e:
        return DAGConfigResult(
            path=str(path),
            evidence=evidence,
            parse_error=str(e),
        )

    if not isinstance(data, dict):
        return DAGConfigResult(path=str(path), evidence=evidence)

    models: list[str] = []
    sources: list[str] = []
    source_tables: list[str] = []
    model_dependencies: dict[str, list[str]] = {}

    # dbt schema: models: [ { name: "model_name", ... }, ... ]
    models_block = data.get("models")
    if isinstance(models_block, list):
        for item in models_block:
            if isinstance(item, dict) and "name" in item:
                model_name = str(item["name"])
                models.append(model_name)
                deps: list[str] = []
                depends_on = item.get("depends_on")
                if isinstance(depends_on, dict):
                    refs = depends_on.get("refs")
                    if isinstance(refs, list):
                        for r in refs:
                            if isinstance(r, str):
                                deps.append(r)
                if deps:
                    model_dependencies[model_name] = sorted(set(deps))
    elif isinstance(models_block, dict):
        # dbt sometimes uses models: project: [ { name: ... } ]
        for project_models in models_block.values():
            if isinstance(project_models, list):
                for item in project_models:
                    if isinstance(item, dict) and "name" in item:
                        model_name = str(item["name"])
                        models.append(model_name)

    # dbt sources: sources: [ { name: "source_name", ... }, ... ]
    sources_block = data.get("sources")
    if isinstance(sources_block, list):
        for item in sources_block:
            if isinstance(item, dict) and "name" in item:
                source_name = str(item["name"])
                sources.append(source_name)
                tables = item.get("tables")
                if isinstance(tables, list):
                    for table in tables:
                        if isinstance(table, dict) and "name" in table:
                            source_tables.append(f"{source_name}.{table['name']}")
    elif isinstance(sources_block, dict):
        for project_sources in sources_block.values():
            if isinstance(project_sources, list):
                for item in project_sources:
                    if isinstance(item, dict) and "name" in item:
                        source_name = str(item["name"])
                        sources.append(source_name)
                        tables = item.get("tables")
                        if isinstance(tables, list):
                            for table in tables:
                                if isinstance(table, dict) and "name" in table:
                                    source_tables.append(f"{source_name}.{table['name']}")

    return DAGConfigResult(
        path=str(path),
        evidence=evidence,
        models=models,
        sources=sources,
        source_tables=source_tables,
        model_dependencies=model_dependencies,
    )
