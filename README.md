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

- Enable LLM-powered semantic analysis (purpose statements, Day-One answers):
  - `uv run python -m src.cli analyze run --repo /path/to/repo --llm`
  - Requires `CARTOGRAPHER_LLM_PROVIDER` and provider-specific env vars (see below).

## LLM and environment variables

When you pass `--llm`, the Semanticist phase uses the provider set in the environment.

| Variable | Description |
|----------|-------------|
| `CARTOGRAPHER_LLM_PROVIDER` | `ollama`, `openai`, or `anthropic` (omit or `none` = disabled). |

**Ollama** (local):

- `OLLAMA_BASE_URL` — default `http://localhost:11434`
- `OLLAMA_MODEL_FAST` — model for bulk summaries (default `llama3.2`)
- `OLLAMA_MODEL_SLOW` — model for synthesis (default same as fast)

**OpenAI** (or compatible API):

- `OPENAI_API_KEY` — required
- `OPENAI_BASE_URL` — optional (e.g. Azure)
- `OPENAI_MODEL_FAST` — e.g. `gpt-4o-mini`
- `OPENAI_MODEL_SLOW` — e.g. `gpt-4o`

**Anthropic**:

- `ANTHROPIC_API_KEY` — required
- `ANTHROPIC_MODEL_FAST` — e.g. `claude-3-5-haiku-20241022`
- `ANTHROPIC_MODEL_SLOW` — e.g. `claude-3-5-sonnet-20241022`

Example (Ollama): `export CARTOGRAPHER_LLM_PROVIDER=ollama OLLAMA_MODEL_FAST=llama3.2` then run with `--llm`.

## Development

- Install dependencies (uv):
  - `uv sync`

- Run tests:
  - `pytest`

## Safety

This project MUST NOT execute untrusted repository code. Analysis is static (read/parse) only.

