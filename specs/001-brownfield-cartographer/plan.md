# Implementation Plan: The Brownfield Cartographer (Agent-by-Agent)

**Branch**: `001-brownfield-cartographer` | **Date**: 2026-03-11 | **Spec**: `specs/001-brownfield-cartographer/spec.md`
**Input**: Feature specification from `/specs/001-brownfield-cartographer/spec.md`

## Summary

Deliver a production-grade, multi-agent codebase intelligence system that can ingest a
real production repository and generate a living architectural map, a data lineage DAG,
and onboarding artifacts (CODEBASE.md + Day-One brief) with evidence and traceability.

Implementation will proceed **one agent at a time** in pipeline order, with explicit
“stop-and-validate” checkpoints after each phase so the system is usable early:

Foundation → Surveyor → Hydrologist → Archivist (MVP docs) → Semanticist → Navigator
→ Incremental mode + hardening.

## Technical Context

**Language/Version**: Python 3.12.7  
**Primary Dependencies**: Pydantic (2.8.2), NetworkX (3.3), Typer (0.24.1), Rich (13.7.1)  
**Storage**: Filesystem artifacts under `.cartography/` (JSON, Markdown, JSONL, vector index directory)  
**Testing**: pytest (9.0.2)  
**Target Platform**: macOS/Linux CLI (local paths; optional GitHub URL support)  
**Project Type**: CLI tool + library modules  
**Performance Goals**: Usable initial map within minutes; support 100k+ LOC repos; parallel file analysis where safe  
**Constraints**: No execution of repo code; static analysis only; evidence required; idempotent outputs  
**Scale/Scope**: Python + SQL + YAML + notebooks; real-world repos with 50+ files; incremental mode best-effort

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify compliance with `.specify/memory/constitution.md`:

- **Core Principles**: Spec-first, evidence-driven analysis, knowledge graph as source of truth
- **Architectural Laws**: Agent boundaries (Surveyor, Hydrologist, Semanticist, Archivist, Navigator), idempotent pipelines
- **Development Protocol**: Spec and plan exist; tasks derived from plan; logging/traceability
- **Relevant sections**: Agent Design Standards, Data Governance, LLM Usage Policy, Artifact Standards, Security Rules, FDE Readiness as applicable to the feature
- **Project Structure**: Source layout matches constitution (src/cli.py, orchestrator, models/, analyzers/, agents/, graph/); artifacts under .cartography/

## Project Structure

### Documentation (this feature)

```text
specs/001-brownfield-cartographer/
├── spec.md
├── plan.md              # This file
├── tasks.md             # Generated later via /speckit.tasks (implementation breakdown)
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/
├── cli.py
├── orchestrator.py
├── models/
│   ├── nodes.py
│   ├── edges.py
│   ├── graphs.py
│   └── evidence.py
├── analyzers/
│   ├── tree_sitter_analyzer.py
│   ├── sql_lineage.py
│   └── dag_config_parser.py
├── agents/
│   ├── surveyor.py
│   ├── hydrologist.py
│   ├── semanticist.py
│   ├── archivist.py
│   └── navigator.py
└── graph/
    └── knowledge_graph.py

tests/
├── unit/
├── integration/
└── contract/

.cartography/
└── (generated outputs per run; not committed by default)

README.md
pyproject.toml
uv.lock
```

**Structure Decision**: Single-project CLI/library with constitution-mandated `src/` layout,
typed graph schemas (Pydantic), and all artifacts under `.cartography/`.

## Implementation Strategy (One Phase / One Agent at a Time)

This plan is intentionally **agent-by-agent**. Each phase ends with concrete artifacts and
validation steps so you can stop after any phase and still have a useful tool.

### Phase 0 — Foundation (Repo skeleton + run loop)

**Goal**: Make a runnable CLI that creates `.cartography/`, emits a trace, and can run an
empty pipeline without crashing.

**Deliverables**

- Create `pyproject.toml` and lock dependencies with `uv` (produce `uv.lock`).
- Create `README.md` with install + run instructions for `analyze` (query later).
- Create skeleton package layout under `src/` per constitution.
- Define baseline Pydantic models: evidence reference (file + line range), node/edge base types,
  and a minimal graph serialization contract.
- Implement `.cartography/` output root creation and a minimal `cartography_trace.jsonl` writer.
- Implement `src/cli.py` with `analyze --repo <path-or-url> --out .cartography/`.
- Implement `src/orchestrator.py` that runs agents in sequence (initially no-op) and records
  phase boundaries to the trace.

**Stop-and-validate**

- Running `analyze` on any directory produces:
  - `.cartography/cartography_trace.jsonl` with at least: run_start, phase_start/phase_end, run_end.
  - No repo code execution (static file reads only).

### Phase 1 — Surveyor (Static structure → module graph)

**Goal**: Build structural skeleton: module import graph, public API surface extraction,
complexity signals, and git velocity signals. Produce `.cartography/module_graph.json`.

**Dependencies introduced in this phase**

- Python tree-sitter bindings + grammars (install as Python deps; avoid shelling out to repo code).

**Key design constraints**

- Surveyor MUST only emit structure facts (no lineage, no LLM).
- Every extracted fact MUST include evidence (file path + line range when applicable).

**Deliverables**

- `src/analyzers/tree_sitter_analyzer.py`: LanguageRouter + AST queries for:
  - Python imports, functions, classes
  - YAML key discovery for pipeline configs (minimal)
  - SQL file discovery (structure only; lineage in Hydrologist)
- `src/agents/surveyor.py`:
  - Build module import graph (NetworkX DiGraph)
  - Identify hubs (PageRank) and SCCs (cycles)
  - Record git velocity (last 90 days) per file
  - Flag dead-code candidates (exported/public items with no references — best-effort)
- Serialize module graph to `.cartography/module_graph.json` with schema metadata.
- Trace entries for file counts, parse failures, and summary stats.

**Stop-and-validate**

- Running `analyze` on a real repo produces `.cartography/module_graph.json`.
- Parse failures appear in trace and do not abort the run.
- Output is idempotent for the same repo state (excluding timestamps in trace).

### Phase 2 — Hydrologist (SQL + pipeline lineage → lineage graph)

**Goal**: Build the DataLineageGraph (datasets + transformations) across SQL, Python,
and YAML/config boundaries. Produce `.cartography/lineage_graph.json`.

**Dependencies introduced in this phase**

- `sqlglot` (not currently installed; add via `uv add sqlglot`).

**Deliverables**

- `src/analyzers/sql_lineage.py`: parse `.sql` and dbt models; extract table dependencies from
  SELECT/FROM/JOIN/WITH; capture evidence line ranges.
- `src/analyzers/dag_config_parser.py`: extract topology from dbt YAML and/or Airflow-like configs
  (start with dbt schema.yml and refs).
- `src/agents/hydrologist.py`:
  - Build lineage DAG (NetworkX DiGraph)
  - Implement graph queries: `trace_upstream(dataset)`, `trace_downstream(dataset)`,
    `find_sources()`, `find_sinks()`, `blast_radius(module_or_dataset)`
  - Represent unresolved/dynamic references explicitly (do not omit)
- Serialize lineage graph to `.cartography/lineage_graph.json`.
- Trace lineage extraction coverage: files scanned, datasets found, unresolved refs.

**Stop-and-validate**

- For a repo with SQL/dbt, you can answer “what produces dataset X?” with a traversal
  (even if surfaced via a simple CLI subcommand initially).

### Phase 3 — Archivist (MVP artifacts: CODEBASE.md + onboarding brief)

**Goal**: Convert structural + lineage graphs into **human-usable** onboarding artifacts with
evidence. This makes the tool valuable even before LLM work.

**Deliverables**

- `src/agents/archivist.py`:
  - Generate `.cartography/CODEBASE.md` with stable structure:
    architecture overview, critical path (top hubs), data sources/sinks, known debt (cycles),
    high-velocity files (git), and an index of modules.
  - Generate `.cartography/onboarding_brief.md` answering the five Day-One questions using
    static signals wherever possible; clearly mark unknowns.
  - Ensure every claim includes evidence or points back to a graph node with evidence.
- Expand trace coverage: artifact generation steps, counts, and timings.

**Stop-and-validate**

- Cold start demo works: run `analyze` → CODEBASE.md + onboarding brief exist under `.cartography/`.
- Outputs are reproducible from graph state.

### Phase 4 — Semanticist (LLM purpose + drift + domain clustering)

**Goal**: Add semantic purpose statements grounded in code evidence; detect doc drift; build
semantic index; support Day-One synthesis improvements.

**Dependencies introduced in this phase**

- An embeddings provider + vector store (choose one and lock it). Keep it minimal and auditable.
- LLM client library (configurable; must degrade gracefully if unavailable).

**Deliverables**

- `src/agents/semanticist.py`:
  - Purpose statements per module/function grounded in code snippets (not docstrings)
  - Documentation drift flags when docstring contradicts observed behavior (best-effort)
  - Domain clustering (start with simple heuristics or lightweight embeddings; avoid heavy compiled deps
    until locked and compatible)
  - `ContextWindowBudget` + cost accounting and caching
- Semantic index written under `.cartography/semantic_index/` with traceable IDs.
- Archivist updated to include purpose statements in CODEBASE.md and brief where available.

**Stop-and-validate**

- When LLM is disabled/unavailable: pipeline still completes with static artifacts.
- When enabled: semantic additions show citations and model metadata in trace.

### Phase 5 — Navigator (Query interface over the graphs)

**Goal**: Provide a query mode (interactive or CLI) that can answer:
find_implementation, trace_lineage, blast_radius, explain_module, with citations and method.

**Dependencies introduced in this phase**

- `langgraph` (not currently installed; add and lock when you begin this phase).

**Deliverables**

- `src/agents/navigator.py`: read-only query agent over the persisted graph/artifacts.
- CLI subcommand `query` that supports:
  - Structured queries (`--trace-lineage dataset --direction upstream`)
  - Natural language query (optional; must cite sources and indicate method).

**Stop-and-validate**

- Required demo steps are possible via CLI query:
  - lineage query + citations
  - blast radius query + citations

### Phase 6 — Incremental mode + hardening (Practicality)

**Goal**: Make runs incremental and robust on real messy repos.

**Deliverables**

- Incremental update mode based on repo diff/commit info; re-analyze only changed paths where possible.
- Stable artifact layout and version metadata; cache invalidation rules documented.
- Performance improvements: parallel file parsing where safe; avoid global locks; cap memory usage.
- Test suite expansion:
  - Integration fixture repo(s)
  - Contract tests for Pydantic schemas
  - Regression tests for parse failures and dynamic refs

**Stop-and-validate**

- Running twice with a small change updates only affected outputs and logs what changed.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |

