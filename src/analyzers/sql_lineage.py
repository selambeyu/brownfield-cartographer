"""
SQL lineage extraction using sqlglot.

Parses .sql and dbt model files to extract table dependencies from
SELECT/FROM/JOIN/WITH (CTE) chains. Supports PostgreSQL, BigQuery, Snowflake, DuckDB.
Emits evidence (file path + line range) for lineage edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

import sqlglot
import sqlglot.expressions as exp

from ..models.evidence import EvidenceRef


# Dialects we support for parsing (sqlglot names).
SUPPORTED_DIALECTS = ("postgres", "bigquery", "snowflake", "duckdb", "mysql", None)


def _table_key(t: exp.Table) -> str:
    """Normalize table to a string key: catalog.schema.name or schema.name or name."""
    parts: list[str] = []
    if t.catalog:
        parts.append(t.catalog)
    if t.db:
        parts.append(t.db)
    parts.append(t.name or "")
    return ".".join(p for p in parts if p)


def _collect_tables(expression: exp.Expression) -> set[str]:
    """Collect all table names referenced in an expression (including subqueries)."""
    out: set[str] = set()
    for node in expression.walk():
        if isinstance(node, exp.Table):
            out.add(_table_key(node))
    return out


def _collect_tables_without_subqueries(expression: exp.Expression) -> set[str]:
    """Collect table names only in FROM/JOIN (not inside subquery selects)."""
    out: set[str] = set()
    for node in expression.walk():
        if isinstance(node, exp.Table):
            # Skip if we're inside a subquery (Table under a Select that is a child of another Select)
            out.add(_table_key(node))
    return out


@dataclass
class SQLLineageResult:
    """Result of parsing one SQL file for lineage."""

    path: str
    evidence: EvidenceRef
    # Table written by this statement (INSERT INTO x, CREATE TABLE x AS, or model output).
    target_table: str | None = None
    # All source tables referenced (FROM, JOIN, subqueries, CTEs).
    source_tables: list[str] = field(default_factory=list)
    # CTE name -> list of table/cte names it references (for DAG ordering).
    cte_dependencies: dict[str, list[str]] = field(default_factory=dict)
    # Raw SELECT (for CREATE/INSERT) or main query.
    parse_error: str | None = None


def extract_sql_lineage(
    path: str,
    source: str,
    dialect: str | None = None,
) -> SQLLineageResult:
    """
    Extract table lineage from a SQL file.

    Args:
        path: File path for evidence.
        source: SQL source text.
        dialect: sqlglot dialect name (postgres, bigquery, snowflake, duckdb, etc.).

    Returns:
        SQLLineageResult with target_table, source_tables, cte_dependencies, and evidence.
    """
    lines = source.count("\n") + 1
    evidence = EvidenceRef(path=path, line_start=1, line_end=lines)

    parse_error: str | None = None
    parsed: list[exp.Expression | None] | None = None

    # Try requested dialect first, then fall back across supported dialects.
    # This improves coverage for mixed SQL/dbt repositories.
    if dialect is not None:
        dialect_candidates: list[str | None] = [dialect]
    else:
        dialect_candidates = list(SUPPORTED_DIALECTS)

    for d in dialect_candidates:
        try:
            parsed = sqlglot.parse(source, dialect=d)
            parse_error = None
            break
        except Exception as e:
            parse_error = str(e)
            parsed = None

    if parsed is None:
        return SQLLineageResult(
            path=path,
            evidence=evidence,
            parse_error=parse_error or "Failed to parse SQL",
        )

    if not parsed:
        return SQLLineageResult(path=path, evidence=evidence)

    # Use first statement for single-statement files; for multi-statement we combine.
    all_sources: set[str] = set()
    target: str | None = None
    cte_deps: dict[str, list[str]] = {}

    for statement in parsed:
        # sqlglot can return None-like entries for unsupported/opaque commands.
        # Skip them instead of failing the whole Hydrologist phase.
        if statement is None:
            continue
        try:
            stmt = statement.unnest()
        except Exception:
            continue
        if stmt is None:
            continue
        if isinstance(stmt, exp.Insert):
            # INSERT INTO target SELECT ... FROM sources
            target_expr = stmt.this
            if isinstance(target_expr, exp.Table):
                target = _table_key(target_expr)
            elif isinstance(target_expr, exp.Schema):
                for tbl in target_expr.find_all(exp.Table):
                    target = _table_key(tbl)
                    break
            query = stmt.expression
            if query is not None:
                all_sources |= _collect_tables(query)
            # Also collect from the insert target if it's a table (already done).
        elif isinstance(stmt, exp.Create):
            # CREATE TABLE x AS SELECT ...
            if stmt.this:
                if isinstance(stmt.this, exp.Table):
                    target = _table_key(stmt.this)
                elif isinstance(stmt.this, exp.Schema):
                    for table in stmt.this.find_all(exp.Table):
                        target = _table_key(table)
                        break
                else:
                    target = str(stmt.this)
            if getattr(stmt, "expression", None):
                all_sources |= _collect_tables(stmt.expression)
        elif isinstance(stmt, exp.Select):
            # Standalone SELECT or dbt model: no explicit target; caller may use filename/model name.
            all_sources |= _collect_tables(stmt)
            # CTEs
            with_ = stmt.args.get("with_")
            if with_:
                for cte in with_.expressions:
                    cte_name = cte.alias
                    cte_query = cte.this
                    refs = list(_collect_tables(cte_query))
                    cte_deps[cte_name] = refs
                    all_sources.update(refs)
        else:
            # MERGE, UPDATE, etc.
            all_sources |= _collect_tables(stmt)
            for table in stmt.find_all(exp.Table):
                # First table might be target in UPDATE/MERGE.
                if target is None and isinstance(stmt, (exp.Update, exp.Merge)):
                    target = _table_key(table)
                    break

    # If we found a target, remove it from sources to avoid self-loops
    if target and target in all_sources:
        all_sources.discard(target)

    return SQLLineageResult(
        path=path,
        evidence=evidence,
        target_table=target,
        source_tables=sorted(all_sources),
        cte_dependencies=cte_deps,
    )


def _strip_jinja(source: str) -> str:
    """
    Best-effort removal of dbt/Jinja templating so sqlglot can parse the remaining SQL.

    We remove:
      - Block tags: {% ... %}, {%- ... -%}
      - Expression tags: {{ ... }}
      - Comment tags: {# ... #}

    This is intentionally conservative: when a file is mostly macros, the result may
    be empty (no lineage), but we avoid hard parse errors while keeping real SQL.
    """
    # Remove Jinja/ dbt comments first
    s = re.sub(r"\{#.*?#\}", " ", source, flags=re.DOTALL)
    # Preserve dbt ref/source calls as SQL-friendly placeholders for lineage.
    # {{ ref('model_name') }} -> model_name
    s = re.sub(
        r"\{\{\s*ref\(\s*['\"]([A-Za-z0-9_./-]+)['\"][^)]*\)\s*\}\}",
        lambda m: m.group(1).replace("-", "_").replace("/", "_").replace(".", "_"),
        s,
        flags=re.IGNORECASE,
    )
    # {{ source('schema_name', 'table_name') }} -> schema_name.table_name
    s = re.sub(
        r"\{\{\s*source\(\s*['\"]([A-Za-z0-9_./-]+)['\"]\s*,\s*['\"]([A-Za-z0-9_./-]+)['\"][^)]*\)\s*\}\}",
        lambda m: f"{m.group(1).replace('-', '_').replace('/', '_')}.{m.group(2).replace('-', '_').replace('/', '_')}",
        s,
        flags=re.IGNORECASE,
    )
    # {{ this }} -> current_model (dbt relation placeholder)
    s = re.sub(r"\{\{\s*this\s*\}\}", "current_model", s, flags=re.IGNORECASE)
    # Remove block tags (macros, control flow)
    s = re.sub(r"\{%-?.*?-%\}", " ", s, flags=re.DOTALL)
    s = re.sub(r"\{%.*?%\}", " ", s, flags=re.DOTALL)
    # Replace remaining inline expressions with SQL-safe literal.
    s = re.sub(r"\{\{.*?\}\}", " 0 ", s, flags=re.DOTALL)
    return s


def _extract_dbt_dependencies(source: str) -> set[str]:
    """
    Extract table/model dependencies directly from dbt Jinja references.

    This makes dbt a first-class lineage input even when SQL parsing is partial.
    - ref('model') -> model
    - source('schema', 'table') -> schema.table
    """
    deps: set[str] = set()
    for m in re.finditer(r"ref\(\s*['\"]([A-Za-z0-9_./-]+)['\"][^)]*\)", source, flags=re.IGNORECASE):
        deps.add(m.group(1))
    for m in re.finditer(
        r"source\(\s*['\"]([A-Za-z0-9_./-]+)['\"]\s*,\s*['\"]([A-Za-z0-9_./-]+)['\"][^)]*\)",
        source,
        flags=re.IGNORECASE,
    ):
        deps.add(f"{m.group(1)}.{m.group(2)}")
    return deps


def extract_tables_from_sql_string(sql: str) -> tuple[list[str], str | None]:
    """
    Parse a SQL string and return (source_tables, target_table).
    Used for inline SQL in Python (e.g. SQLAlchemy execute()).
    """
    res = extract_sql_lineage("<inline>", sql)
    if res.parse_error:
        return ([], None)
    return (res.source_tables, res.target_table)


def extract_sql_lineage_from_file(
    file_path: str | Path,
    dialect: str | None = None,
) -> SQLLineageResult:
    """Read file from disk and extract SQL lineage."""
    path = Path(file_path)
    if not path.exists():
        return SQLLineageResult(
            path=str(path),
            evidence=EvidenceRef(path=str(path)),
            parse_error="File not found",
        )
    # dbt macro files are template libraries, not executable model SQL.
    # Skip them to avoid noisy parse errors and false lineage.
    if "macros" in path.parts:
        return SQLLineageResult(
            path=str(path),
            evidence=EvidenceRef(path=str(path), line_start=1, line_end=1),
            target_table=None,
            source_tables=[],
            cte_dependencies={},
            parse_error=None,
        )

    source = path.read_text(encoding="utf-8", errors="replace")
    dbt_deps = _extract_dbt_dependencies(source)
    # Many dbt projects include Jinja macros and control flow in .sql files.
    # Strip templating before handing to sqlglot so we avoid parse errors on
    # tokens like `{% macro ... %}` while still extracting lineage from the
    # underlying SELECT / INSERT / CREATE statements.
    cleaned = _strip_jinja(source)
    res = extract_sql_lineage(str(path), cleaned, dialect=dialect)

    # First-class dbt lineage fallback: preserve ref()/source() deps even if
    # sqlglot cannot fully parse templated model SQL.
    if dbt_deps:
        merged_sources = sorted(set(res.source_tables) | dbt_deps)
        if res.parse_error:
            return SQLLineageResult(
                path=res.path,
                evidence=res.evidence,
                target_table=res.target_table,
                source_tables=merged_sources,
                cte_dependencies=res.cte_dependencies,
                parse_error=None,
            )
        res.source_tables = merged_sources

    return res
