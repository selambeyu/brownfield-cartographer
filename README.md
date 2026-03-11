# The Brownfield Cartographer

The Brownfield Cartographer is a multi-agent codebase intelligence system that analyzes large
production repositories and generates a living architectural map of the system.

## Outputs

All generated artifacts are written under `.cartography/` (by default), including:

- `module_graph.json`
- `lineage_graph.json`
- `CODEBASE.md`
- `onboarding_brief.md`
- `cartography_trace.jsonl`
- `semantic_index/` (when enabled)

**Lineage graph** (`lineage_graph.json`): Built by the Hydrologist from SQL (sqlglot), dbt/YAML config, and Python data-flow (pandas/SQLAlchemy/PySpark read/write). Use it to answer “Show me all upstream dependencies of table X” and “What would break if I change the schema of table Y?”  
**Blast radius**: From any dataset or transformation node, `blast_radius(graph, node_id)` returns all downstream datasets and transformations (BFS). Entry/exit points: `find_sources(graph)` (in-degree 0) and `find_sinks(graph)` (out-degree 0). Unresolved/dynamic references are kept in the graph with `is_unresolved=True` and in the trace (no silent omission).

## Usage (early scaffold)

> Use `uv run` so the project virtualenv + dependencies are used consistently.

- Analyze a local repository:
  - `uv run python -m src.cli analyze run --repo /path/to/repo --out .cartography/`

- Analyze a Git URL (cloned to a temp dir and removed on exit):
  - `uv run python -m src.cli analyze run --repo https://github.com/octocat/Hello-World.git --out .cartography/`

## Development

- Install dependencies (uv):
  - `uv sync`

- Run tests:
  - `pytest`

## Safety

This project MUST NOT execute untrusted repository code. Analysis is static (read/parse) only.

