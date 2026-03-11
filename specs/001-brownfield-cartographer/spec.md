# Feature Specification: The Brownfield Cartographer

**Feature Branch**: `001-brownfield-cartographer`  
**Created**: 2025-03-10  
**Status**: Draft  
**Input**: Create specification for the project based on TRP 1 Challenge Week 4 — The Brownfield Cartographer

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate Living Architecture Map (Priority: P1)

As a forward-deployed engineer (FDE) arriving at a new client, I need to run the Cartographer against the codebase once and receive a structured architectural overview so that I can understand modules, entry points, critical path, and dead code within minutes instead of days.

**Why this priority**: Without a system map, the FDE cannot orient. This is the foundation for all other value (lineage, briefs, querying).

**Independent Test**: Run the tool against a repository path; receive a single coherent architecture document and a module dependency graph. Verify that the document lists modules, identifies highly connected (critical) modules, and flags likely dead code.

**Acceptance Scenarios**:

1. **Given** a local or remote repository path, **When** the user runs the analysis command, **Then** the system produces an architecture overview and a module graph under the configured output directory.
2. **Given** a codebase with at least 50 files and multiple languages, **When** analysis completes, **Then** the output includes which files import which, and which modules are architectural hubs (most imported).
3. **Given** a codebase with rarely or never imported symbols, **When** analysis completes, **Then** the output surfaces dead-code candidates with evidence (file and line).

---

### User Story 2 - Trace Data Lineage and Blast Radius (Priority: P2)

As an FDE, I need to ask “what produces this dataset?” and “what breaks if I change this module?” and get answers with file and line citations so that I can safely change pipelines and assess impact.

**Why this priority**: Data lineage and blast radius are the highest-leverage questions in data engineering engagements; they directly reduce risk and speed up changes.

**Independent Test**: Run analysis, then run a lineage query for a known output table and a blast-radius query for a known module. Answers must cite source file and line range.

**Acceptance Scenarios**:

1. **Given** a codebase containing SQL and/or pipeline config, **When** the user asks for upstream sources of a named dataset, **Then** the system returns a directed graph of dependencies with transformation type, source file, and line range.
2. **Given** a module path, **When** the user asks for blast radius (what would break if this module changed), **Then** the system returns all downstream dependents with evidence.
3. **Given** mixed Python, SQL, and config (e.g., dbt, Airflow), **When** lineage is requested, **Then** the system traces data flow across language boundaries and reports entry points (sources) and exit points (sinks).

---

### User Story 3 - Get Day-One Brief and Query via Natural Language (Priority: P3)

As an FDE, I need an auto-generated Day-One Brief that answers the five critical onboarding questions with evidence, and a query interface so I can ask natural-language questions about the codebase and get answers grounded in the architectural map and lineage.

**Why this priority**: The brief and query interface multiply the value of the map and lineage by making them immediately consumable and searchable.

**Independent Test**: After a full run, open the onboarding brief and confirm it answers the five Day-One questions with citations; run at least one natural-language query and confirm the answer includes file/line evidence and whether it came from static analysis or inference.

**Acceptance Scenarios**:

1. **Given** a completed analysis run, **When** the user opens the onboarding brief, **Then** it contains structured answers to: (1) primary data ingestion path, (2) 3–5 most critical output datasets/endpoints, (3) blast radius of the most critical module, (4) where business logic is concentrated vs. distributed, (5) what changed most in the last 90 days (change velocity), each with evidence (file path and line or range).
2. **Given** the query interface is available, **When** the user asks “Where is the revenue calculation logic?” or “What produces the daily_active_users table?”, **Then** the system returns an answer that cites source file and line and indicates the method (static analysis vs. inference).
3. **Given** the living context file (CODEBASE.md), **When** it is injected into an AI coding agent session, **Then** that agent can answer architecture questions about the codebase using the injected context.

---

### User Story 4 - Incremental and Auditable Runs (Priority: P4)

As an FDE or maintainer, I need to re-run analysis on only changed files when the repo has new commits, and I need a trace log of every analysis action so that I can audit how results were produced and debug failures.

**Why this priority**: Incremental runs make the tool practical for ongoing use; traceability is required for trust and debugging.

**Independent Test**: Run full analysis, make a small change in the repo, run again in incremental mode; verify only affected artifacts are updated. Inspect the trace log and confirm each agent action and evidence source is recorded.

**Acceptance Scenarios**:

1. **Given** a previous successful run and new commits in the repo, **When** the user runs analysis in incremental mode, **Then** the system re-analyzes only changed paths (or documents what was skipped) and updates artifacts without requiring a full rescan.
2. **Given** any run, **When** the user inspects the trace output, **Then** every agent action (Surveyor, Hydrologist, Semanticist, Archivist) is logged with inputs, outcomes, and evidence or error details.
3. **Given** a run that encounters parse or external failures, **When** the run completes, **Then** the system produces partial results where safe, marks failures or uncertainty in the trace and/or graph, and does not abort the entire pipeline for recoverable failures.

---

### Edge Cases

- What happens when the repository is very large (e.g., 100k+ lines)? The system must complete or stream progress and document time-to-first-artifact and time-to-full-artifacts; it must not require disproportionate resources by default.
- What happens when a file cannot be parsed (syntax error, unsupported language)? The system must skip or mark that file, record the failure in the trace, and continue with the rest of the codebase.
- What happens when lineage cannot be fully resolved (e.g., dynamic table names, runtime config)? The system must represent unknown or dynamic references explicitly (e.g., “dynamic reference, cannot resolve”) rather than silently omitting them.
- What happens when the user points the tool at a non-repository path or an empty directory? The system must fail with a clear, actionable error and not produce misleading artifacts.
- What happens when external services (e.g., LLM APIs) are unavailable or rate-limited? The system must degrade gracefully: static-only artifacts (map, lineage) still produced; semantic artifacts (purpose statements, Day-One answers) marked partial or skipped and recorded in the trace.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept a repository path (local directory or GitHub URL) and produce a living architectural map (modules, imports, critical path, dead-code candidates) with evidence (file path and line or range).
- **FR-002**: The system MUST build and expose a data lineage graph (sources, transformations, sinks) across Python, SQL, and config boundaries, with transformation type, source file, and line range on each edge.
- **FR-003**: The system MUST support queries for upstream dependencies of a dataset and for blast radius of a module (downstream dependents), with answers citing file and line.
- **FR-004**: The system MUST produce an onboarding brief that answers the five Day-One questions (ingestion path, critical outputs, blast radius of critical module, concentration of business logic, recent change velocity) with evidence citations.
- **FR-005**: The system MUST produce a living context file (CODEBASE.md) suitable for injection into an AI coding agent, with structured sections (e.g., architecture overview, critical path, data sources/sinks, known debt, change velocity, module purpose index).
- **FR-006**: The system MUST produce a serialized module graph and lineage graph (e.g., JSON) and a semantic index (vector store) of module purpose statements for search, with results traceable to source (file/line or node id).
- **FR-007**: The system MUST log every agent action to a trace file (e.g., cartography_trace.jsonl) with agent name, phase, inputs, outcomes, and evidence or error details.
- **FR-008**: The system MUST support an incremental update mode that re-analyzes only changed files or commits when possible and documents what was updated.
- **FR-009**: The system MUST NOT execute repository code (no import, eval, or subprocess of repo scripts); only static analysis (read, parse, AST) is allowed.
- **FR-010**: The system MUST store all generated artifacts under a single configurable output root (e.g., .cartography/) with documented, stable paths and naming.
- **FR-011**: The system MUST provide a query interface (e.g., natural language and/or structured) that returns answers citing source file, line range, and analysis method (static vs. inference).
- **FR-012**: When parsing or an external call fails, the system MUST fail gracefully: emit partial results where safe, mark failure or uncertainty in the graph or trace, and MUST NOT crash the entire pipeline for recoverable failures.

### Key Entities

- **Repository**: The target codebase (local path or GitHub URL); the primary input to analysis.
- **Module**: A file or logical unit in the codebase; has path, language, imports, public API, complexity signals, change velocity, and optional purpose statement and domain cluster.
- **Dataset**: A table, file, stream, or API that appears in lineage; has name, storage type, and optional schema/freshness/owner.
- **Transformation**: A step in the data pipeline that consumes and/or produces datasets; has source/target datasets, type, source file, and line range.
- **Knowledge graph**: The unified store of structural and lineage facts (modules, functions, datasets, transformations, and edges such as IMPORTS, PRODUCES, CONSUMES, CALLS, CONFIGURES).
- **Artifacts**: Generated outputs (CODEBASE.md, onboarding_brief.md, module_graph, lineage_graph, semantic index, trace file) derived from the knowledge graph and stored under the output root.
- **Trace**: The audit log of agent actions, evidence sources, and errors for a run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can run the tool against an unfamiliar repository and receive a usable architectural overview (e.g., CODEBASE.md and onboarding brief) within minutes (e.g., under 15 minutes for a 10k-line repo on standard hardware).
- **SC-002**: For a data-engineering codebase (e.g., dbt or Airflow), the lineage graph produced by the system matches the expected upstream/downstream relationships for at least two known output datasets, with file and line citations.
- **SC-003**: The onboarding brief correctly answers at least four of the five Day-One questions when verified against manual inspection of the codebase (with at least two answers verified by navigating to the cited file and line).
- **SC-004**: When the living context file is injected into an AI coding agent, that agent can correctly answer at least one architecture question about the codebase that it cannot answer without the context.
- **SC-005**: The system supports repositories of at least 100k lines of code without requiring disproportionate resources; time-to-first-artifact and time-to-full-artifacts are documented.
- **SC-006**: Every agent action is recorded in the trace; an auditor can reconstruct why a given fact appears in the graph or in generated docs by following evidence and the trace.
- **SC-007**: On parse or external failure, the system produces partial results and a clear trace of what failed; the pipeline does not abort entirely for recoverable failures.

## Assumptions

- The primary users are forward-deployed engineers (FDEs) and technical leads who need to onboard quickly to brownfield data-engineering or data-science codebases.
- Target codebases include Python, SQL, YAML, and notebooks; the system is not required to support every possible language in the first release.
- A single run is sufficient to produce the core artifacts (map, lineage, brief); the query interface and semantic search may require a prior full or incremental run.
- Evidence means at least file path and line number (or range); “analysis method” means whether a fact came from static analysis or from an inference step (e.g., LLM).
- The five Day-One questions are fixed for this feature; they are: (1) primary data ingestion path, (2) 3–5 most critical output datasets/endpoints, (3) blast radius of the most critical module, (4) where business logic is concentrated vs. distributed, (5) what changed most in the last 90 days.
- Incremental mode is best-effort: the system will re-analyze changed files when feasible and document what was updated; full rescans remain available.
