<!--
Sync Impact Report
==================
Version: 1.0.0 → 1.1.0
Modified principles: N/A
Added sections: Project Structure (canonical repo layout, src/, agents, analyzers, graph, artifacts)
Removed sections: N/A
Templates: plan-template.md ✅ (Constitution Check references Project Structure);
  spec-template.md (no change); tasks-template.md (no change); commands/ not present
Follow-up TODOs: None
-->

# The Brownfield Cartographer — Project Constitution

## Preamble

This constitution governs the development of **The Brownfield Cartographer**, a multi-agent
codebase intelligence system built using Spec-Kit Driven Development. The system analyzes
large production repositories (Python, SQL, YAML, notebooks), performs static and semantic
analysis, and produces a living architectural map. All design and implementation decisions
MUST conform to the principles and rules defined herein. The constitution is the source of
authority for architectural, developmental, and operational standards.

---

## Core Principles

### I. Engineering Philosophy

- The system MUST be designed for **real production codebases**: large, messy, and
  evolving. Assumptions MUST NOT rely on clean or toy repositories.
- **Spec-first development** is mandatory: features are specified, planned, and broken
  into tasks before implementation. No implementation without an approved spec and plan.
- Complexity MUST be justified. Prefer simple, deterministic mechanisms over heuristics
  or inference where both are feasible.
- The system MUST be **maintainable by a small team**. Documentation, structure, and
  observability are first-class requirements, not afterthoughts.

### II. System Reliability

- Analysis pipelines MUST be **idempotent**: re-running on the same repository state MUST
  produce equivalent results (modulo non-determinism explicitly documented and bounded).
- Agents MUST **fail gracefully** when parsing or external calls fail: partial results
  and clear error signals are required; unhandled exceptions that abort the entire run
  are prohibited for recoverable failures.
- The system MUST support **incremental updates**: re-analysis of only changed paths or
  commits where technically feasible, to keep artifacts fresh without full rescans.
- All outputs MUST be **serializable** and **reproducible** from a given repo state and
  configuration; reproducibility is a contract, not best-effort.

### III. Code Intelligence Design

- **Static analysis is preferred over inference.** Use AST parsing (tree-sitter), SQL
  parsing (sqlglot), and graph construction (NetworkX) for structural and lineage facts.
  LLMs are used only where static analysis cannot provide the required semantic signal.
- **Evidence is mandatory.** Every analysis result that can be attributed to source code
  MUST include evidence: file path, and line number or range. Inferred or LLM-derived
  claims MUST cite the snippet or context used.
- The **knowledge graph is the source of truth.** All structural and lineage facts flow
  into a single, typed graph. Artifacts (CODEBASE.md, briefs, indexes) are derived from
  the graph, not from ad-hoc aggregation.
- **Domain and purpose understanding** are first-class: the system MUST produce
  machine-readable and human-readable descriptions of modules and data flows to support
  onboarding and exploration.

### IV. Evidence-Driven Analysis

- No claim about the codebase (purpose, dependency, lineage, risk) MAY be emitted
  without traceability to either (a) static analysis output with file/line evidence, or
  (b) an LLM call with explicit input context and citation in the output schema.
- Ambiguity or parse failures MUST be represented explicitly in the graph or artifacts
  (e.g., unknown lineage, parse_error nodes) rather than silently omitted.
- Auditors MUST be able to reconstruct why a given fact appears in the graph or in
  generated docs by following evidence and logs.

---

## Architectural Laws

### Agent Boundaries

- **Surveyor**: Sole responsibility is static structure—module graphs, imports, functions,
  complexity signals, git velocity. MUST NOT perform lineage or semantic inference.
- **Hydrologist**: Sole responsibility is data lineage and data flow—DAG of datasets and
  transformations (e.g., SQL, notebook cells). MUST consume structural output; MUST NOT
  alter structural facts.
- **Semanticist**: Sole responsibility is LLM-based extraction of purpose statements and
  domain understanding. MUST operate on already-extracted snippets and metadata; MUST NOT
  replace or duplicate static parsing.
- **Archivist**: Sole responsibility is generating and persisting artifacts (CODEBASE.md,
  onboarding_brief.md, module_graph.json, lineage_graph.json, semantic index). MUST read
  from the knowledge graph and configured outputs only; MUST NOT introduce new analysis.
- **Navigator**: Sole responsibility is querying the knowledge graph and answering user
  questions. MUST be read-only over the graph and artifacts; MUST NOT mutate graph or
  run analysis agents.

### Knowledge Graph as Source of Truth

- The unified graph (NetworkX-based, with defined node and edge types) is the single
  representation of structural and lineage facts. All agents that produce facts MUST
  write into this graph (or a designated subgraph/schema) under a defined contract.
- Artifacts (markdown, JSON, vector index) are **views** derived from the graph. They
  MUST be regenerable from the graph and config; no artifact MAY be the only store of
  critical facts.
- Graph schema (node types, edge types, required attributes) is defined in code and
  enforced via Pydantic and validation steps. Ad-hoc node or edge types are prohibited.

### Idempotent Analysis Pipelines

- A full run on commit C with config K MUST produce the same graph state (and
  deterministic artifacts) on repeated runs, except where documented non-determinism
  exists (e.g., LLM sampling). Non-determinism MUST be bounded and explicitly listed.
- Pipeline stages MUST be orderable and replayable. Dependencies between agents (e.g.,
  Surveyor before Hydrologist, both before Semanticist) MUST be explicit and enforced.

---

## Development Protocol

### Spec-First Workflow

- New features or major changes REQUIRE a feature specification under `specs/[###-feature-name]/spec.md`,
  created via the Spec-Kit specification workflow. The spec MUST include user scenarios,
  acceptance criteria, and success criteria.
- An implementation plan (`plan.md`) MUST be produced from the spec before implementation.
  The plan MUST reference this constitution and include a Constitution Check that verifies
  compliance with Core Principles and relevant Architectural Laws.
- Tasks are derived from the plan and spec (e.g., via `/speckit.tasks`). Implementation
  MUST follow the task ordering and checkpoints; tasks MAY not be skipped without
  updating the plan and documenting justification.

### Proposal and Implementation

- Proposals that affect architecture, agent boundaries, graph schema, or artifact
  contracts MUST be documented (spec or ADR) and reviewed for constitution compliance.
- Implementation MUST preserve backward compatibility of artifacts and graph schema
  unless a deliberate breaking change is specified and versioned (e.g., artifact version
  field, migration path).

### Testing and Validation

- Unit tests MUST cover parsing, graph construction, and artifact generation for
  representative and edge-case inputs. Parsing and graph logic MUST NOT rely solely on
  integration tests.
- Integration tests MUST cover at least: full pipeline on a fixture repo, incremental
  run, and Navigator query path. At least one test MUST run against a real-world-sized
  fixture (e.g., 10k+ LOC) to validate performance assumptions.
- Contract tests or schema tests MUST ensure Pydantic models and graph node/edge types
  remain consistent across changes.

### Logging and Traceability

- All agent invocations and major pipeline steps MUST be logged in a structured way.
  Agent outputs that affect the graph or artifacts MUST be traceable to the run and
  configuration.
- The system MUST produce `cartography_trace.jsonl` (or equivalent) recording agent
  actions, decisions, and errors for each run. Trace format MUST be documented and
  stable for audit and debugging.

---

## Agent Design Standards

- **Single responsibility**: Each agent has one clearly defined responsibility; no agent
  MAY take on parsing, lineage, semantic, and archival duties in one.
- **Evidence in results**: Every analysis result (node, edge, or derived field) that
  comes from code MUST include evidence (file path, and line or range). LLM-derived
  results MUST include the cited context and model info in the schema.
- **Graceful failure**: On parse failure, unsupported construct, or external API failure,
  the agent MUST emit partial results where safe, mark failure or uncertainty in the
  graph or trace, and MUST NOT crash the pipeline unless the failure is unrecoverable
  and documented.
- **Serializable outputs**: All agent outputs MUST be serializable (e.g., Pydantic
  models, JSON-serializable dicts). No in-memory-only or non-persistable state may be
  the only representation of a fact.

---

## Data Governance

### Pydantic Schema Enforcement

- All inputs and outputs of agents, and all graph node/edge payloads, MUST be defined
  with Pydantic models. Ad-hoc dicts are prohibited for public APIs and persisted data.
- Schema changes that affect persisted artifacts or the graph MUST be versioned and
  migration or compatibility MUST be addressed in the spec.

### Graph Consistency Rules

- Node and edge types MUST be declared in a central schema. Only allowed types MAY be
  added to the graph. Attributes MUST conform to the schema (required fields, types).
- Cycles in lineage (e.g., SQL) MUST be detected and handled per policy (e.g., break
  edge, mark cycle). The graph MUST remain valid for traversal and query.

### Dataset Lineage Validation

- Lineage edges MUST reference source and target entities that exist in the graph.
  Orphan lineage edges or references to non-existent nodes are invalid and MUST be
  rejected or repaired by the pipeline.
- Lineage semantics (e.g., “table A read by query Q”) MUST be explicit in the edge type
  and attributes; validation MUST run after Hydrologist (and any other lineage-producing
  agent) to ensure consistency.

### Node and Edge Typing Standards

- Naming MUST be consistent: e.g., `Module`, `Function`, `Dataset`, `Query`, `LineageEdge`.
  Typing MUST be documented and enforced in code. New types require a schema update and
  constitution-compliant justification.

---

## LLM Usage Policy

- **No LLMs for deterministic parsing.** Lexing, AST parsing, SQL parsing, and
  structural extraction MUST use tree-sitter, sqlglot, or equivalent. LLMs MUST NOT be
  used to replace or bypass these for facts that can be obtained by static analysis.
- **Static analysis first.** Design MUST prefer static analysis for structure and
  lineage. LLMs are used only for semantic understanding (purpose, domain, summaries)
  that cannot be derived from syntax alone.
- **Evidence and citations.** Every LLM-derived result MUST include: (a) the exact
  input context (e.g., file path, snippet, line range), and (b) where applicable, a
  citation or confidence indicator in the output schema. Non-citable LLM output is not
  acceptable for architectural or lineage claims.
- **Cost-aware model selection.** Model choice (e.g., local vs. API, model size) MUST
  be configurable. Defaults MUST be documented. High-volume or batch LLM use MUST be
  justified and, where possible, bounded (e.g., sampling, caching, batching).

---

## Artifact Standards

- **CODEBASE.md**: MUST be structured and machine-readable (e.g., clear headings,
  optional frontmatter or sections that can be parsed). It MUST reflect the current
  graph state and MUST be regenerable from the graph. It is the primary “living
  architecture” artifact.
- **onboarding_brief.md**: MUST serve as the FDE Day-One Brief: concise, actionable,
  and aligned with the Five Day-One FDE Questions. Format and required sections MUST
  be defined and stable.
- **module_graph.json**, **lineage_graph.json**: MUST be valid JSON representations of
  the corresponding subgraphs or views, with a documented schema. They MUST be
  reproducible from the same repo and config.
- **Semantic vector index**: MUST be keyed or documentable so that results can be
  traced back to source (file/line or node id). Index build MUST be reproducible from
  graph + config where embeddings are deterministic.
- **Storage**: All generated artifacts MUST be stored under `.cartography/` (or a
  single configured output root). Paths and naming MUST be documented so that
  tooling and users can rely on a stable layout.
- **Reproducibility**: Given repository state (commit, ref) and configuration, artifact
  generation MUST be reproducible except for explicitly documented non-determinism
  (e.g., LLM, timestamps). Version or generation metadata SHOULD be present in
  artifacts where useful for cache invalidation and debugging.

---

## Observability Rules

- **Unified trace**: All agent actions MUST be logged to `cartography_trace.jsonl` (or
  the configured trace path) for each run. Entries MUST include agent name, phase,
  inputs (e.g., paths or scope), outcomes (success/partial/failure), and evidence or
  error details as appropriate.
- **Source evidence**: Every result that can be tied to source code MUST include at
  least file path and line number (or range). This applies to graph nodes/edges and to
  generated narrative (e.g., CODEBASE.md, briefs). Evidence format MUST be consistent
  and documented.
- **Incremental support**: The system MUST support incremental updates (e.g., only
  changed files or commits). Trace and artifacts MUST allow understanding what was
  updated in a run and what was reused from a previous state.

---

## Performance Requirements

- The system MUST support repositories with **100k+ lines of code** without requiring
  disproportionate resources. Design and defaults (e.g., parallelism, chunking, batch
  size) MUST be justified for this scale.
- **Parallel analysis** MUST be used where safe: independent files or modules MAY be
  processed in parallel; ordering constraints (e.g., graph writes) MUST be enforced.
- **Incremental analysis** on new commits or changed paths MUST be supported. Full
  rescans MUST not be the only option for keeping artifacts up to date. Incremental
  behavior MUST be documented and tested.

---

## Security Rules

- **No execution of untrusted repo code.** The system MUST NOT execute user or
  repository code (e.g., import, eval, subprocess of repo scripts). Only static
  analysis (file read, parse, AST) is allowed. Any exception (e.g., safe sandbox for
  a specific use case) MUST be explicitly justified and documented.
- **Static analysis only.** No dynamic execution of repository code for the purpose of
  analysis. Scripts or notebooks are analyzed as text/AST/SQL only.
- **Secrets and configuration:** Environment and config (API keys, credentials) MUST be
  handled via safe patterns (e.g., env vars, config files outside repo, no logging of
  secrets). Repo contents MUST NOT be assumed safe; sensitive patterns in analyzed
  content SHOULD be handled per policy (e.g., redaction in logs or artifacts).

---

## FDE Readiness Criteria

- The system MUST answer the **Five Day-One FDE Questions** (or the project’s current
  definition thereof) using the knowledge graph and generated artifacts. The mapping
  from questions to artifacts or queries MUST be documented.
- The system MUST produce a **usable architectural overview within minutes** of running
  on a new repository (e.g., CODEBASE.md and onboarding_brief.md available after a
  single run). Time-to-first-artifact and time-to-full-artifacts SHOULD be measured and
  documented.
- Outputs MUST **prioritize developer onboarding value**: structure, entry points,
  data flow, and “where to start” MUST be clearly exposed in the brief and in the
  query interface (Navigator).

---

## Project Structure

The repository MUST follow the canonical layout defined below. New components MUST be
placed in the designated directories; ad-hoc or duplicate entry points are prohibited.

### Source Layout (Repository Root)

- **src/cli.py**: Single entry point. MUST accept repo path (local or GitHub URL) and
  subcommands (e.g., `analyze`, `query`). No other CLI entry points for the Cartographer.
- **src/orchestrator.py**: Wires Surveyor → Hydrologist → Semanticist → Archivist in
  sequence; serializes outputs to `.cartography/`. MUST NOT contain analysis logic.
- **src/models/**: All Pydantic schemas: node types (ModuleNode, DatasetNode,
  FunctionNode, TransformationNode), edge types, and graph types. No analysis code here.
- **src/analyzers/tree_sitter_analyzer.py**: Multi-language AST parsing with
  LanguageRouter (Python, SQL, YAML, etc.). MUST be the single tree-sitter integration point.
- **src/analyzers/sql_lineage.py**: sqlglot-based SQL dependency extraction for lineage.
- **src/analyzers/dag_config_parser.py**: Airflow/dbt YAML config parsing for pipeline
  topology. Parsers for DAG and schema config live here.
- **src/agents/surveyor.py**: Surveyor agent—module graph, PageRank, git velocity, dead
  code candidates. MUST consume analyzers; MUST NOT perform lineage or semantic analysis.
- **src/agents/hydrologist.py**: Hydrologist agent—DataLineageGraph, blast_radius,
  find_sources/find_sinks. MUST consume structural and config output.
- **src/agents/semanticist.py**: Semanticist agent—LLM purpose statements, doc drift
  detection, domain clustering, Day-One question answering, ContextWindowBudget.
- **src/agents/archivist.py**: Archivist agent—CODEBASE.md, onboarding_brief.md, trace
  logging. Reads from graph only; MUST NOT introduce new analysis.
- **src/agents/navigator.py**: Navigator agent—LangGraph query interface with tools
  (find_implementation, trace_lineage, blast_radius, explain_module). Read-only over graph.
- **src/graph/knowledge_graph.py**: NetworkX wrapper with serialization. Single
  representation of the unified graph; all agents read/write via this module.

### Dependency and Documentation

- **pyproject.toml**: MUST use locked dependencies (e.g., uv lock). No unversioned or
  floating deps for production runs.
- **README.md**: MUST document how to install and run: at least `analyze` (and `query`
  when Navigator is implemented). Target codebase requirements and artifact locations MUST
  be described.

### Artifact Output Layout

- All Cartography artifacts MUST be written under **.cartography/** (or a single
  configured output root). Required outputs: `module_graph.json`, `lineage_graph.json`,
  `CODEBASE.md`, `onboarding_brief.md`, `cartography_trace.jsonl`, and `semantic_index/`
  (vector store) when the Semanticist is implemented. Paths and naming MUST match
  Artifact Standards.

### Tests and Specs

- **tests/**: Unit, integration, and contract tests per Development Protocol. Layout MAY
  mirror `src/` (e.g., `tests/unit/`, `tests/integration/`, `tests/contract/`).
- **specs/**: Feature specifications and plans per Spec-Kit workflow (`specs/[###-feature-name]/`).

Deviations from this structure REQUIRE a constitution-compliant justification and
documentation in the spec or ADR.

---

## Governance

- This constitution supersedes ad-hoc practices. All design and implementation
  decisions MUST comply with the principles and rules above. Where compliance is
  ambiguous, the team MUST resolve by updating the constitution or the implementation
  and documenting the outcome.
- **Amendments**: Changes to the constitution require (a) a documented proposal, (b)
  impact assessment (principles, agents, artifacts, templates), and (c) version bump
  per semantic versioning: MAJOR for backward-incompatible governance or principle
  changes, MINOR for new principles or material expansion, PATCH for clarifications and
  typos.
- **Compliance**: Feature specs and implementation plans MUST include a Constitution
  Check. PRs that affect architecture, agents, graph schema, or artifact contracts MUST
  be reviewed for constitution compliance. Violations MUST be justified in the plan or
  resolved before merge.
- **Runtime guidance**: Use this document as the authority for development and
  architecture. Project-specific runbooks or quickstart docs MUST reference the
  constitution where they prescribe design or behavior.

**Version**: 1.1.0 | **Ratified**: 2025-03-10 | **Last Amended**: 2025-03-10
