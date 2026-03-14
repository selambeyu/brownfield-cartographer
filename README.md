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
- `semantic_index/` (`modules.json`, `domains.json`, `day_one_answers.json`, and `vector_db/`)

**Lineage graph** (`lineage_graph.json`): Built by the Hydrologist from SQL (sqlglot), dbt/YAML config, and Python data-flow (pandas/SQLAlchemy/PySpark read/write). Use it to answer “Show me all upstream dependencies of table X” and “What would break if I change the schema of table Y?”  
**Blast radius**: From any dataset or transformation node, `blast_radius(graph, node_id)` returns all downstream datasets and transformations (BFS). Entry/exit points: `find_sources(graph)` (in-degree 0) and `find_sinks(graph)` (out-degree 0). Unresolved/dynamic references are kept in the graph with `is_unresolved=True` and in the trace (no silent omission).

## Usage (early scaffold)

> Use `uv run` so the project virtualenv + dependencies are used consistently.

- Analyze a local repository:
  - `uv run python -m src.cli analyze run --repo /path/to/repo --out .cartography/`
  - Incremental mode: `uv run python -m src.cli analyze run --repo /path/to/repo --incremental`
  - Disable LLM explicitly: `uv run python -m src.cli analyze run --repo /path/to/repo --no-llm`

- Analyze a Git URL (cloned to a temp dir and removed on exit):
  - `uv run python -m src.cli analyze run --repo https://github.com/octocat/Hello-World.git --out .cartography/`

- Enable LLM-powered semantic analysis (purpose statements, Day-One answers):
  - `uv run python -m src.cli analyze run --repo /path/to/repo --llm`
  - Requires `CARTOGRAPHER_LLM_PROVIDER` and provider-specific env vars (see below).

- Structured and natural-language query modes:
  - `uv run python -m src.cli query trace-lineage --dataset <dataset_name> --direction upstream`
  - `uv run python -m src.cli query blast-radius --node <dataset_or_node>`
  - `uv run python -m src.cli query explain-module --path src/agents/hydrologist.py`
  - `uv run python -m src.cli query ask --question "What produces dataset customers?"`
  - Implementation lookup queries now use vector similarity over purpose statements when `semantic_index/vector_db` exists.

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

## Integration Fixture + Smoke Protocol

Use the fixture in `tests/fixtures/sample_dag.py` to validate end-to-end behavior quickly.

1. Run full analysis:
   - `uv run python -m src.cli analyze run --repo . --out .cartography --no-llm`
2. Run incremental analysis after a small edit:
   - `uv run python -m src.cli analyze run --repo . --out .cartography --incremental --no-llm`
3. Smoke queries:
   - `uv run python -m src.cli query trace-lineage --dataset customers --direction upstream`
   - `uv run python -m src.cli query blast-radius --node dataset:customers`
   - `uv run python -m src.cli query ask --question "What breaks if customers changes?"`
4. Verify artifacts exist:
   - `.cartography/module_graph.json`
   - `.cartography/lineage_graph.json`
   - `.cartography/CODEBASE.md`
   - `.cartography/onboarding_brief.md`
   - `.cartography/cartography_trace.jsonl`
   - `.cartography/run_metadata.json`

## Safety

This project MUST NOT execute untrusted repository code. Analysis is static (read/parse) only.
The orchestrator enforces a strict policy: no repo code execution, and only metadata git commands
(`rev-parse`, `diff`) are allowed for incremental scope detection.

