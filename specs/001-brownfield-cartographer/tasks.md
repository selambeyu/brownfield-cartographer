---

description: "Actionable task list for The Brownfield Cartographer implementation"
---

# Tasks: The Brownfield Cartographer

**Input**: Design documents from `/specs/001-brownfield-cartographer/`  
**Prerequisites**: `plan.md` (required), `spec.md` (required for user stories)  
**Tests**: Not explicitly requested in the spec; tasks below focus on implementation and validation checkpoints.  
**Organization**: Tasks are grouped by user story (US1–US4) and ordered to support **one phase / one agent at a time**.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Every task includes an exact file path

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Initialize repository skeleton per constitution and make the project runnable.

- [x] T001 Create constitution-mandated directories `src/`, `tests/`, and output root `.cartography/` (dirs only)
- [x] T002 Create `pyproject.toml` with base metadata and dependency management (uv-ready)
- [x] T003 Create `README.md` with installation + `analyze` usage and artifact locations
- [x] T004 [P] Create `src/models/` module files: `src/models/evidence.py`, `src/models/nodes.py`, `src/models/edges.py`, `src/models/graphs.py`
- [x] T005 [P] Create `src/graph/knowledge_graph.py` skeleton with load/save placeholders
- [x] T006 [P] Create agent skeleton files: `src/agents/surveyor.py`, `src/agents/hydrologist.py`, `src/agents/archivist.py`, `src/agents/semanticist.py`, `src/agents/navigator.py`
- [x] T007 [P] Create analyzer skeleton files: `src/analyzers/tree_sitter_analyzer.py`, `src/analyzers/sql_lineage.py`, `src/analyzers/dag_config_parser.py`
- [x] T008 Create `.gitignore` to exclude `.cartography/` and common Python build artifacts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T009 Implement trace schema + writer in `src/models/evidence.py` (run metadata + file/line evidence reference types)
- [x] T010 Implement minimal typed graph container + serialization contract in `src/models/graphs.py`
- [x] T011 Implement KnowledgeGraph wrapper (NetworkX + typed node/edge payloads) in `src/graph/knowledge_graph.py`
- [x] T012 Implement orchestrator pipeline shell in `src/orchestrator.py` (phase boundaries, agent sequencing, trace events)
- [x] T013 Implement CLI entrypoint in `src/cli.py` with `analyze --repo ... --out ...` (no analysis yet)
- [x] T014 Implement artifact output root handling in `src/orchestrator.py` (create `.cartography/`, write `cartography_trace.jsonl`)
- [x] T015 Add run configuration model (repo path, output root, flags) in `src/models/graphs.py` (or dedicated config model file if preferred)

**Checkpoint**: Foundation ready — `python -m src.cli analyze run --repo <path>` writes `.cartography/cartography_trace.jsonl` and exits cleanly.

---

## Phase 3: User Story 1 — Generate Living Architecture Map (Priority: P1) 🎯 MVP

**Goal**: Produce a structural map (imports/module graph, critical hubs, dead-code candidates) with evidence.

**Independent Test**: Run `analyze` on a real repo; verify `.cartography/module_graph.json` is created and trace logs parse failures without aborting.

### Implementation for User Story 1 (Surveyor)

- [x] T016 [US1] Define Module/Function/Class node types and IMPORTS/CALLS edge types in `src/models/nodes.py` and `src/models/edges.py`
- [x] T017 [US1] Implement LanguageRouter + file discovery in `src/analyzers/tree_sitter_analyzer.py` (Python/SQL/YAML/Notebook discovery)
- [x] T018 [US1] Add tree-sitter grammars (Python/SQL/YAML/JS/TS) to `pyproject.toml` (LanguageRouter uses `tree-sitter-languages`)
- [x] T019 [US1] Implement Python import + function/class extraction in `src/analyzers/tree_sitter_analyzer.py` (emit evidence ranges)
- [x] T020 [US1] Implement Surveyor agent to build module import graph + stats in `src/agents/surveyor.py`
- [x] T021 [US1] Implement `extract_git_velocity(path, days=30)` in `src/agents/surveyor.py` (git log parsing)
- [x] T022 [US1] Implement hub ranking (PageRank) + cycle detection (SCC) in `src/agents/surveyor.py`
- [x] T023 [US1] Implement best-effort dead-code candidate heuristics in `src/agents/surveyor.py` and record rationale in trace
- [x] T024 [US1] Wire Surveyor into `src/orchestrator.py` and serialize module graph to `.cartography/module_graph.json`

**Checkpoint**: `.cartography/module_graph.json` exists and contains typed nodes/edges; trace includes parse failures and summary stats.

### Phase 3 Addendum — Surveyor Phase 1 completeness (post-MVP)

- [x] T054 [US1] Extend `ModuleNode` to include public API signatures + complexity signals + dead-code candidates in `src/models/nodes.py`
- [x] T055 [US1] Extract function signatures, cyclomatic complexity, and comment ratio in `src/analyzers/tree_sitter_analyzer.py`
- [x] T056 [US1] Add JS/TS import extraction + import edges (best-effort) in `src/analyzers/tree_sitter_analyzer.py` and `src/agents/surveyor.py`
- [x] T057 [US1] Implement dead-code candidate detection for exported Python symbols in `src/agents/surveyor.py`
- [x] T058 [US1] Emit Surveyor metrics to trace (dead-code count, avg complexity/comment ratio) in `src/orchestrator.py`

---

## Phase 4: User Story 2 — Trace Data Lineage and Blast Radius (Priority: P2)

**Goal**: Build a lineage DAG across SQL + config boundaries and provide blast radius / upstream queries with evidence.

**Independent Test**: Run `analyze` on a dbt-like repo; verify `.cartography/lineage_graph.json` exists; run an upstream traversal for a known dataset and get file/line citations.

### Implementation for User Story 2 (Hydrologist)

- [x] T025 [US2] Define Dataset/Transformation node types and PRODUCES/CONSUMES/CONFIGURES edges in `src/models/nodes.py` and `src/models/edges.py`
- [x] T026 [US2] Add `sqlglot` dependency to `pyproject.toml`
- [x] T027 [US2] Implement SQL lineage extraction (tables + CTE dependencies) in `src/analyzers/sql_lineage.py` with evidence ranges
- [x] T028 [US2] Implement dbt/YAML topology extraction (schema.yml + refs best-effort) in `src/analyzers/dag_config_parser.py`
- [x] T029 [US2] Implement Hydrologist lineage graph builder in `src/agents/hydrologist.py` (merge SQL + config analyzers)
- [x] T030 [US2] Implement lineage queries in `src/agents/hydrologist.py`: `trace_upstream`, `trace_downstream`, `find_sources`, `find_sinks`
- [x] T031 [US2] Implement blast radius traversal in `src/agents/hydrologist.py` for dataset + module inputs (document behavior in README)
- [x] T032 [US2] Wire Hydrologist into `src/orchestrator.py` and serialize `.cartography/lineage_graph.json`
- [x] T033 [US2] Ensure unresolved/dynamic references are represented explicitly in the graph and trace (no silent omission) in `src/agents/hydrologist.py`

**Checkpoint**: `.cartography/lineage_graph.json` exists; hydrologist traversal returns upstream/downstream datasets with evidence.

---

## Phase 5: User Story 3 — Day-One Brief and Query via Natural Language (Priority: P3)

**Goal**: Generate `CODEBASE.md` and `onboarding_brief.md` from the graphs, and expose a query interface that returns citations and method.

**Independent Test**: After `analyze`, open `.cartography/onboarding_brief.md` and confirm it answers the five Day-One questions with citations; run a query command and confirm output cites file/line and method.

### Implementation for User Story 3 (Archivist → Navigator baseline)

- [ ] T034 [US3] Define artifact schemas/metadata (artifact version, run id, repo ref) in `src/models/graphs.py`
- [ ] T035 [US3] Implement Archivist artifact generator in `src/agents/archivist.py` to write `.cartography/CODEBASE.md`
- [ ] T036 [US3] Implement onboarding brief generator in `src/agents/archivist.py` to write `.cartography/onboarding_brief.md` (five Day-One answers; unknowns explicitly marked)
- [ ] T037 [US3] Ensure every statement in artifacts links back to evidence (file/line) or to a graph node with evidence in `src/agents/archivist.py`
- [ ] T038 [US3] Wire Archivist into `src/orchestrator.py` after Surveyor + Hydrologist
- [ ] T039 [US3] Add initial structured query CLI subcommands in `src/cli.py` (no LangGraph yet): `trace-lineage`, `blast-radius`, `explain-module`
- [ ] T040 [US3] Implement the structured query handlers in `src/agents/navigator.py` (read-only over persisted graphs)

**Checkpoint**: `.cartography/CODEBASE.md` and `.cartography/onboarding_brief.md` exist; CLI can run at least one lineage query + one blast-radius query with citations.

---

## Phase 6: User Story 4 — Incremental and Auditable Runs (Priority: P4)

**Goal**: Re-run only changed files when possible; record a complete audit trace of all agent actions and decisions; degrade gracefully on failures.

**Independent Test**: Run `analyze` twice with a small repo change; verify trace shows incremental scope and only affected artifacts changed; verify parse failures do not abort.

### Implementation for User Story 4 (Incremental + Robustness)

- [ ] T041 [US4] Implement stable run id + run metadata capture in `src/orchestrator.py` and trace writer (`cartography_trace.jsonl`)
- [ ] T042 [US4] Implement incremental scope detection (git diff or file mtimes) in `src/orchestrator.py`
- [ ] T043 [US4] Implement per-agent incremental interfaces (accept changed paths; document “best-effort” semantics) in `src/agents/surveyor.py` and `src/agents/hydrologist.py`
- [ ] T044 [US4] Implement artifact regeneration rules (what gets recomputed vs reused) in `src/agents/archivist.py`
- [ ] T045 [US4] Standardize error reporting and graceful-failure envelopes across agents in `src/models/evidence.py` and agent implementations
- [ ] T046 [US4] Add CLI flags to control incremental mode and LLM enable/disable in `src/cli.py` (LLM can be stubbed until Semanticist is built)

**Checkpoint**: Incremental run updates only affected outputs; trace explicitly records changed paths and what was recomputed vs reused.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates, performance, and completing optional advanced capabilities (Semanticist + LangGraph Navigator).

- [ ] T047 [P] Add `langgraph` dependency and implement natural-language query mode in `src/agents/navigator.py` (keep structured mode intact)
- [ ] T048 [P] Implement Semanticist scaffolding + “LLM off” graceful degradation in `src/agents/semanticist.py`
- [ ] T049 Implement semantic index layout under `.cartography/semantic_index/` and update Archivist to include purpose statements in `.cartography/CODEBASE.md`
- [ ] T050 Add performance instrumentation (timings per phase, file counts) to trace in `src/orchestrator.py`
- [ ] T051 Add parallel file parsing where safe (bounded worker pool) in `src/analyzers/tree_sitter_analyzer.py`
- [ ] T052 Add basic integration fixture + smoke scripts (non-test) to `README.md` describing how to validate on a target repo
- [ ] T053 Harden security guarantees (no repo execution) by documenting and enforcing allowed operations in `src/orchestrator.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — produces module graph MVP
- **US2 (Phase 4)**: Depends on US1 + Foundational — produces lineage graph
- **US3 (Phase 5)**: Depends on US1 + US2 — produces CODEBASE.md + onboarding brief + structured query CLI
- **US4 (Phase 6)**: Depends on US3 — incremental + audit hardening
- **Polish (Phase 7)**: Depends on desired US completion; Semanticist/LangGraph can be layered after US3

### User Story Dependencies

- **US1 (P1)**: No dependencies beyond foundation
- **US2 (P2)**: Builds on structural extraction; depends on US1 outputs
- **US3 (P3)**: Depends on graphs from US1 and US2
- **US4 (P4)**: Depends on a working pipeline to make incremental/audit meaningful

---

## Parallel Example (within a single agent phase)

```text
# Setup phase parallel tasks:
T004 (models/*) and T005 (graph wrapper) and T006/T007 (skeleton agent/analyzer files)

# US1 phase parallel tasks:
T016 (models) can be developed while T017 (router/discovery) starts.
```

