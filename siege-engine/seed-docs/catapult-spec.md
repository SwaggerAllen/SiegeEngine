# Catapult — Specification

Catapult is the industrial-strength successor to Siege Engine. It is an AI-powered document generation and code scaffolding system that takes a project description and produces a full tree of design documents and code through a structured, reviewable pipeline. The system uses two interconnected graph structures: a **pipeline DAG** that defines *what work to do* and a **document DAG** that represents *what has been produced*.

This specification is divided into two parts: **A. Requirements** (what the system does) and **B. Architecture** (what technologies are used and how).

---

# Part A — Requirements

## A.1 Core Concepts

### A.1.1 Boulders

A **boulder** is a node in the document DAG that has its own sub-DAG of processing steps (its **boulder template**). Boulders exist at three levels:

- **System** — one per project, the root of the document tree
- **Component** — produced by system-level fan-out
- **Subcomponent** — produced by component-level fan-out; terminal (subcomponents cannot fan out further, two layers of branching maximum)

Leaf boulders are single-use boulders that produce implementation artifacts. A leaf boulder may be a child of a system, component, or subcomponent boulder. Every leaf boulder produces at minimum an implementation plan and a PR commit.

### A.1.2 Repository and Folder Mapping

Each leaf boulder maps to a `{repository, folder}` pair. For v1, all boulders within a project target a single repository (monorepo assumption), but the mapping is structured to support multi-repo projects in the future without a data model change.

Within a repository, each leaf boulder corresponds to a folder — the boulder's territory. This gives a direct, deterministic mapping between the document tree and the codebase. This mapping must be explicitly enforced in prompts and generation.

### A.1.3 Root Boulders

At every fan-out level, there is a **root boulder** that owns files not belonging to any fanned-out child. At the system level this is the "system root component," at the component level this is the "component root subcomponent." The root boulder's intended purpose is build configuration, infrastructure files, and similar cross-cutting concerns, but its contents are not prescribed — different deployments and ecosystems will have different needs.

### A.1.4 Dual DAG Architecture

- **Pipeline DAG**: A directed acyclic graph of processing stages defining the shape of the work — which AI generation steps run, in what order, and with what inputs. The pipeline DAG is a sequence of 5 phases, each containing a configurable boulder template (itself a DAG). When a phase fans out, the boulder template is instantiated once per boulder.
- **Document DAG**: A directed acyclic graph of artifacts (documents and code) produced by the pipeline. Each node is a versioned document with status tracking. Edges represent parent-child relationships and cross-cutting dependency relationships between sibling boulders.
- The pipeline DAG drives generation; the document DAG records results.

## A.2 Flows

The system supports five flow types. Only one flow run (or sub-run) may be active per project at a time.

### A.2.1 Scaffolding Flow

The default flow. Generates all documents from scratch, walking the full document DAG top-down through every boulder.

- At system and component boulders: produces an architecture document and a fan-out node
- At subcomponent boulders: produces an architecture document only (no further fan-out)
- Fan-out nodes produce a document and structured output deciding whether to decompose into child boulders or generate a leaf boulder
- Leaf boulders produce an implementation plan and a PR commit

### A.2.2 Feature Request Flow

Input is a feature description. At each boulder level:

1. A **plan node** takes the expanded input doc and the boulder's current architecture doc, and produces a plan describing what changes are needed at this level to achieve the feature
2. An **architecture update node** takes the plan and updates the architecture doc accordingly
3. The plan propagates downward as input to child boulders' plan nodes

At leaf boulders, the plan from the parent boulder drives PR generation. Each plan builds on its parent's plan, creating a chain of increasingly specific change descriptions from system level down to implementation.

### A.2.3 Refactor Flow

Input is a refactoring objective. Same structure as feature request: plan at each architecture node (taking expanded input + current architecture), update the architecture given the plan, propagate the plan downward to leaf boulders for PR generation.

### A.2.4 Upward Propagation Flow

Always initiated by the user. Used when new requirements discovered at downstream nodes need to propagate through the rest of the system. The algorithm is:

1. **Upward pass**: Walk from the originating node up to the project root, collecting changes at each level
2. **Downward pass**: Walk back down from the root through all fan-out nodes, routing changes to affected children — including children that were not on the original upward path but are impacted by the changes

At fan-out nodes during the downward pass, the system identifies which children need updates. This means an upward propagation can trigger downstream changes in sibling subtrees — e.g., a bug fix that reveals a new requirement may update documentation going up and require code changes in an unrelated component going back down. Upward propagation may also update the expanded requirements document if the discovered changes affect project-level requirements.

### A.2.5 Bug Fix Flow

Input is a PR that fixes a bug (not the bug itself). The system maps changed files back to leaf boulders via the folder mapping (Section A.1.2). From the identified leaf boulders, the flow operates as an upward propagation (Section A.2.4):

1. At each boulder level during the upward pass, a **diagnosis node** produces a diagnosis document analyzing what the PR reveals about the gap between the documented architecture and reality — why the bug existed, what assumption was wrong, what edge case was missed
2. An **architecture update node** takes the diagnosis and updates the architecture doc accordingly
3. Parent nodes wait for all descendant diagnoses to complete before producing their own, so changes from multiple touched leaves are merged into a single coherent diagnosis at each fan-out node

During the downward pass, fan-out routing identifies sibling subtrees impacted by the diagnosed changes. The diagnosis chain serves the same role as the plan chain in feature request/refactor flows — it gives reviewers an explicit, approvable interpretation of what the bug means for the system's design at each level.

## A.3 Phases

Every flow run walks the document DAG in five phases. Each phase has a boulder template defining the processing steps for that phase. Phases correspond directly to tree depth — phase 2 is the system level, phase 3 is the component level, and so on. Downward flows walk phases in order (1→5); upward propagation walks upward through phases then back down, potentially revisiting phases during the downward pass.

1. **Input Expansion** — Takes raw user input and expands it into a structured requirements document (the "expanded input doc")
2. **System Docs** — Produces or updates system-level architecture for the system boulder
3. **Component Docs** — Instantiated once per component boulder; produces or updates component-level architecture
4. **Subcomponent Docs** — Instantiated once per subcomponent boulder; produces or updates subcomponent-level architecture
5. **Leaf Nodes** — Instantiated once per leaf boulder; produces implementation plans and PR commits

### A.3.1 Phase Traversal

A flow run always starts with an input document, expands it into a requirements document (the expanded input doc), then walks the tree from one particular node out to its furthest descendants. At each node it generates or edits one or more documents as defined by its flow type.

### A.3.1.1 Input Document Lifecycle

The raw input document (user-provided) never changes. The **expanded input document** (requirements doc produced by phase 1) is simply the root node of the document DAG. It is not a special case — when a flow traverses the tree and reaches it, it is updated like any other node. When a flow walks downward, it starts from it like any other root.

### A.3.2 Propagation

By default, propagation of changes goes **downward**. At fan-out nodes, the system generates a routing document determining which child nodes to visit.

**Upward propagation** is a two-pass algorithm (see Section A.2.4). During the upward pass, changes are collected bottom-up — parent nodes wait for **all** descendants to complete before updating, so inputs are merged and each parent regenerates only once. During the downward pass, fan-out routing identifies additional children impacted by the merged changes. Upward propagation is always user-initiated.

### A.3.3 Fan-Out

Fan-out nodes are conditional — the AI decides whether decomposition is needed based on complexity. When a fan-out node fires, it produces:
- A list of child boulders with names and descriptions
- A dependency DAG among those boulders specifying execution order
- A root boulder for that level (Section A.1.3) to handle files outside fanned-out folders

Fan-out is bounded: subcomponents are the terminal level. The maximum document tree depth is system → component → subcomponent → leaf.

### A.3.4 Parallel Execution Within Phases

Within a phase or within a boulder template DAG, non-dependent nodes whose parent nodes have completed generation can execute in parallel. Independent sibling boulders (no dependency edges between them) can also be processed in parallel.

### A.3.5 Context Assembly

Input to a document node is assembled from:
- The expanded input document (always included if not otherwise present)
- Direct parent outputs are always included in full
- Ancestor outputs within the same boulder template DAG and from ancestor boulders, included using a **budget-based approach**: include full parent documents in chronological order (nearest ancestors first) until the context budget for ancestors is exhausted. Remaining ancestors are retrieved via semantic relevance from the vector database. This means earlier/shallower nodes in the tree get richer direct context, which is acceptable and arguably desirable — system-level decisions benefit from full context, while leaf nodes work from more focused, relevant excerpts.

Context assembly uses a **strategy pattern** — different flows and phases use different methods for gathering and budgeting context. Architecture nodes need structural context (parent architecture, sibling summaries). Leaf plan nodes need the parent plan plus current code state. Fan-out routing nodes need summary-level understanding of all children. Upward propagation nodes need what changed below and what exists above.

## A.4 Boulder Templates

Each flow has a boulder template for each phase. A boulder template is itself a DAG of processing nodes within the boulder, defining the constellation of prompts used to generate documents for that system/component/subcomponent.

### A.4.1 Template Pinning

When a flow run is scheduled, it pins to the boulder template versions that exist at schedule time. Template updates made after scheduling do not affect in-progress runs. Template updates are queued with flows — the UI shows the queue at project, boulder, and node levels so users can see what version each run is using and what changes are pending.

### A.4.2 Template Visibility and Editability

All nodes in boulder templates are visible to users. Users can see and understand the full processing pipeline. Users can modify boulder templates: adding, removing, or reordering nodes. This is possible because all node types are surfaced in the UI.

## A.5 Sub-Runs

Flow runs can spawn sub-runs. For example, a refactor sub-run during a scaffolding run, or an upward propagation sub-run during a refactor. Only one run or sub-run may be active at a time per project — sub-runs pause their parent run, execute, and then the parent resumes.

When a sub-run completes, the parent run resumes and sees the current state of all nodes — including any modifications made by the sub-run. Nodes that the parent run has not yet processed will simply receive updated context reflecting the sub-run's changes. This is the intended mechanism for handling mid-flow discoveries: if reviewing a component reveals a missing upstream requirement, the user kicks off an upward propagation sub-run, it modifies the relevant upstream nodes, and when the parent resumes, all remaining unprocessed nodes pick up the new context naturally.

## A.6 Review and Approval

Every document and commit produced by the system goes through review:

1. **AI self-review** — The AI reviews its own output with structured feedback (quality score, recommendation, notes). If revision is recommended, the system automatically regenerates incorporating feedback, up to a configurable loop limit.
2. **Human review** — After AI review, artifacts enter "awaiting review" status. Humans approve or reject with text feedback only (no inline edits). Rejection feedback is incorporated in a subsequent AI revision pass.
3. **CI loop** — For code commits, CI results feed back into the generation loop. CI failure is not a bug fix — it means the system generated incorrect code and should retry with the error output as additional context. This is a first-class concept.

### A.6.1 Auto-Approval

Some node types can be configured for auto-approval, skipping human review. This is configurable per node type, per phase, or per project.

### A.6.2 Review Cadence and Granularity

Review gates are configurable: per-node, per-phase, leaves-only, or fully automatic. The default should be sensible but the user controls it.

The intended review workflow is **batched**: the flow produces N documents, then pauses for human review of that batch. The reviewer reads and leaves feedback on some or all documents. Rejected documents and their downstream dependents are then regenerated as a sub-run incorporating the feedback. Once the sub-run completes, the flow resumes and produces the next batch of M documents. This produce-review-regenerate cycle repeats through the flow.

### A.6.3 Restart Semantics

Flow runs support four restart granularities:

- **Node-level** — Regenerate a single node's output; downstream nodes are marked stale
- **Phase-level** — Restart an entire phase; all nodes in that phase are regenerated
- **Flow-level** — Restart the entire flow from input expansion
- **Partial retry** — Retry only failed/rejected nodes within a phase, leaving approved nodes intact

Each restart option clearly communicates what gets invalidated.

### A.6.4 Status Chain

pending → generating → ai_reviewing → awaiting_review → approved / rejected / stale

Rejecting an artifact propagates staleness downstream.

## A.7 Concurrency and Locking

The system uses **pessimistic locking** at the node level. Only one flow run or sub-run may be active per project at a time. This dramatically simplifies the concurrency story:

- No two flows can edit the same boulder simultaneously
- Sub-runs pause their parent, so there is no concurrent modification within a single project
- Lock acquisition follows the tree traversal order
- Locks are released on node completion, failure, or configurable timeout

## A.8 Resumability and Recoverability

- If a flow fails at any node, it can resume from the point of failure without re-running completed nodes
- Completed nodes are idempotent on re-run (re-running a completed node produces a new version but does not invalidate its dependents unless the output differs)
- All state changes are recorded as events, enabling replay and recovery
- Locks are automatically released on failure with configurable timeout

## A.9 Document Storage Model

Document content lives in two places with distinct roles:

- **PostgreSQL** is the operational store for document content. All reads during flow execution, context assembly, and UI rendering come from the database. pgvector embeddings are indexed against DB content directly.
- **Git/Gitea** receives committed snapshots at review boundaries — when a document reaches `awaiting_review` or `approved` status. Working drafts and AI review loops happen entirely in the database without git noise.

This means git history reflects meaningful checkpoints (reviewable and approved states), not every intermediate generation attempt. The event log tracks all state transitions regardless of whether a git commit was produced.

## A.10 Git Strategy

- **One commit per leaf node** — Each leaf boulder produces a single commit
- **One PR per flow run** — All leaf commits from a flow run are composed into a single PR, ordered by dependency structure
- **Sub-run commits** contribute to the parent flow's PR
- Every project is assumed to be a **monorepo** for v1. The data model supports multi-repo via the `{repository, folder}` mapping (Section A.1.2), but v1 flow orchestration, PR composition, and Gitea sidecar integration assume a single repository per project.
- The system is the sole code shipping mechanism for the project (aside from bug fix PRs which are the input, not the output).

## A.11 Document Versioning

- All artifacts are versioned. Each generation or revision produces a new version.
- Event sourcing provides a complete audit trail of every state change.
- Users can revert to any previous version. Reversion appends new events (no destructive history changes).
- Each completed run produces a git commit checkpoint.

## A.12 Prompt System

- Each processing node type has a built-in prompt template with: system message, output format instructions, context assembly template, and revision instructions.
- Users can override any prompt field per stage per project.
- Model and temperature are configurable at three levels: project default, per-phase default, and per-node override. Defaults propagate downward.

## A.13 Credentials and Token Tracking

- The service is **BYO LLM credentials** — customers supply their own API keys through the application, not environment variables. Credentials are stored per-user.
- Token usage is tracked per node, per flow run, and per project. Users can see how many tokens each generation step consumed.
- Cost projection is deferred to a future version, but the tracking infrastructure is in place from day one.

## A.14 Real-Time Updates

- All connected clients receive live updates when artifacts are generated, statuses change, or flows progress.
- DAG visualizations, status indicators, and artifact viewers update in real-time.

## A.15 Auth and Multi-User Access

- Role-based access control: admin (full control), member (run flows, review, configure), viewer (read-only, can comment).
- Invite-based onboarding with time-limited tokens.
- Per-user LLM credential storage.
- Per-user git credential storage for push/PR operations.

## A.16 Multi-Project Support

- Multiple independent projects, each with its own repository, document DAG, pipeline configuration, and event history.
- One active flow run per project at a time; different projects run concurrently.

## A.17 Bootstrap Flow

A one-time flow for self-bootstrapping. The only supported use case is onboarding a codebase that already has all required documents in the correct hierarchy and whose folder structure mirrors the boulder mapping assumptions.

- Takes as input: a codebase with documents already matching the scaffolding flow's output shape (requirements, architectures, plans) organized in the expected hierarchy
- Reconstructs the boulder hierarchy, dependency DAG, and document DAG from the existing documents and folder structure
- Does **not** reconstruct event history or review records — those start fresh from the point of bootstrap
- Destructive to existing project state; can only run once or on a fresh project
- After bootstrap, the project can use any standard flow to iterate

## A.18 AI Coding Assistant Integration

The coding portion of leaf boulder execution (plan creation and PR generation) is delegated to an AI coding assistant. The assistant has tools to read, navigate, and understand the current codebase directly — no separate code parsing or AST indexing is needed. The assistant works up implementation plans since it already has the tools to see the code in context. The document tree provides the "what needs to change" and the coding assistant handles the "how to change it" against the actual code.

## A.19 Operational Invariants (Learned from Siege Engine v1)

These requirements are derived from edge cases, bugs, and hard-won knowledge from Siege Engine's production use. They are non-negotiable for Catapult.

### A.19.1 Dependency Satisfaction

Dependencies are satisfied when a parent artifact has been **generated** (status in: `approved`, `awaiting_review`, `stale`), not only when approved. This allows downstream generation to proceed while upstream is still under human review. Without this, a single slow reviewer blocks the entire pipeline.

### A.19.2 Fan-Out Always Pauses for Review

Fan-out stages (which create or modify the boulder tree structure) must always pause for human review regardless of auto-approval settings. Structural changes — adding, removing, or reorganizing boulders — are too consequential to auto-approve. This is a hard override, not configurable.

### A.19.3 Blocking PR

If an outstanding PR exists for a project from a prior flow run, new flows cannot start. This prevents the document DAG from drifting out of sync with the codebase. The user must merge or close the existing PR before starting a new flow.

### A.19.4 Prune as a Review Action

Beyond approve and reject, users need a **prune** action: remove a downstream cascade that became irrelevant. For example, a fan-out produced a component that shouldn't exist. Reject would regenerate it; prune removes it and all its descendants from the document DAG, emitting appropriate events.

### A.19.5 Cascading Readiness Re-Scan

After completing any node, the orchestrator must re-scan all pending nodes for newly unblocked work — not just the completed node's immediate children. Generating component A's architecture might unblock component B (which depends on A via the dependency DAG), and B may have already been passed in a linear scan. The scan must loop until no more work is found in a single pass.

### A.19.6 Centralized Run Completion

Run completion (transitioning a run to terminal status) must happen through exactly one codepath. Siege Engine had bugs where run completion logic was scattered across multiple callers, causing zombie runs that stayed in RUNNING status indefinitely. The single completion point should be in a `finally`-equivalent block of the main execution loop.

### A.19.7 Phase Boundary Checks Before Execution

Stop-point checks (phase boundaries, user-configured pause points) must be evaluated **before** entering a stage's execution, not after. The check acts as a gate: stages past the stop point are never entered. Checking after execution means boundary-crossing stages run before the pause is detected.

### A.19.8 Cross-Run Execution Deduplication

Before creating a new execution for a node, check for existing RUNNING executions for the same node **across all runs**, not just the current run. Scoping this check to a single run allows duplicate executions when sub-runs or manual triggers overlap.

### A.19.9 Retries Are Sub-Runs

Failed executions are not retried in-place. A retry is a sub-run: it pauses the current run, creates a new run scoped to the failed node, executes, and returns control to the parent. This keeps the execution model uniform — there is no special "retry" concept, just the same sub-run machinery used everywhere else. The original failed execution remains in its terminal state in the event log.

### A.19.10 Git-Before-DB Commit Ordering

When an operation produces both a git commit and a database event, the git commit must happen **before** the database commit. If the database succeeds but git fails, the event log references a nonexistent commit — corrupted event history that is difficult to recover from. If git succeeds but the database fails, the result is an orphaned git commit that can be cleaned up trivially without data loss. Always order: git commit → DB commit.

### A.19.11 Reconciliation on Startup

On server startup, the system must reconcile all projects: rebuild materialized state from events, detect and resolve orphaned executions (RUNNING with no active job → mark FAILED), complete zombie runs (RUNNING with no active executions → mark FAILED), and cancel stale queued jobs. This is a first-class recovery mechanism, not an afterthought.

### A.19.12 LLM Output Parsing Resilience

LLM output format is unreliable. All structured output extraction (component lists, dependency DAGs, code files, plans) must use multiple parsing strategies with fallbacks. Try strict parsing first, fall back to regex extraction, then to smaller-model re-extraction. Never fail a stage because the LLM returned valid content in an unexpected format.

### A.19.13 LLM Concurrency Limits

Parallel execution within phases (A.3.4) must respect a configurable concurrency limit for LLM calls. Siege Engine hardcoded this to 1 after higher values caused resource exhaustion and rate limiting cascades. The limit should be configurable per project but default to conservative values. Exponential backoff on rate limit errors (3 attempts, 1s base delay).

---

# Part B — Architecture

## B.1 Elixir / OTP

The application is built in Elixir on the BEAM VM. OTP provides the concurrency primitives, supervision trees, and fault tolerance model that underpin flow execution, real-time updates, and process management.

## B.2 PostgreSQL

Primary data store for all persistent state: projects, users, credentials, boulder templates, prompt configurations, and materialized views of current pipeline and document state.

## B.3 Commanded (CQRS/ES)

The core domain uses Commanded for command/query responsibility segregation and event sourcing. All state changes to the pipeline and document DAGs are expressed as commands that produce events. Events are the source of truth; materialized read models are derived projections.

This gives us:
- Complete audit trail of every action
- Time travel / revert by replaying events
- Resumability by replaying from the last successful event
- Clean separation between "what happened" and "what the current state looks like"

Commanded's process managers coordinate multi-step workflows (flow runs, phase transitions, boulder execution). Aggregates enforce invariants (pessimistic locking, status transitions, template pinning).

Critical constraint from Siege Engine: the event-sourced snapshot (materialized from events) is the **single source of truth** for all pipeline and document state. There are no duplicate status fields on separate DB model tables — the snapshot is the only place pipeline/document state lives. This eliminates an entire class of bugs (stale projections, sync drift) and simplifies rollback: reverting events is sufficient, there are no secondary tables to reconcile.

## B.4 Oban

Background job processing for work that doesn't fit Commanded's event-driven model: LLM API calls, git operations, CI polling, credential refresh, and other side-effectful operations that need retries, scheduling, and observability. Oban jobs are triggered by Commanded events and emit commands back into the event-sourced domain on completion.

## B.5 pgvector

Vector embeddings stored in PostgreSQL via pgvector for semantic retrieval during context assembly. Document chunks are embedded and indexed so that deep nodes can retrieve relevant ancestor context by semantic similarity rather than consuming entire documents. The retrieval strategy varies by flow and phase (Section A.3.5).

## B.6 Gitea (Sidecar)

A Gitea instance runs as a sidecar handling git hosting, branch management, PR mechanics, and merge conflict resolution. Catapult provides its own review UI via LiveView (Section B.7) — Gitea's web UI is not the primary user-facing interface. Gitea's UI is available as an escape hatch, proxied or iframed for merge conflict resolution and other git edge cases where a purpose-built git UI is needed.

Gitea's role in the system:
- **Git backend** — Branch creation, commit composition, PR lifecycle, merge operations. This avoids reimplementing git operations in Elixir (where git libraries are immature) or shelling out to the git CLI (which has concurrency issues)
- **Merge conflict UI** — For the rare edge cases where conflicts arise despite folder-per-leaf and one-run-at-a-time constraints. Available as a proxied escape hatch, not the primary workflow
- **Webhook events** — Gitea emits granular webhooks for the full PR lifecycle: creation, comments, inline review comments, review submissions (approve/request changes), merges, and branch updates. Catapult subscribes to these webhooks to automate responses to PR activity (e.g., CI feedback triggers regeneration, human review comments on PRs feed back into the review workflow)
- **Programmatic review feedback** — The AI posts review comments (including inline comments tied to file paths and line numbers) via Gitea's API, enabling code review to happen directly on the PR
- **Webhook configuration** — Repo-level webhooks are configured per project; system-level webhooks handle cross-cutting concerns

## B.7 Phoenix / LiveView

Web framework and real-time UI layer. Phoenix Channels provide WebSocket-based live updates. LiveView powers the interactive DAG visualizations, artifact viewers, review interfaces, and template editors. No separate frontend build — the UI is server-rendered with client-side interactivity via LiveView.

## B.8 AI Coding Assistants

Leaf boulder code generation is delegated to AI coding assistants (e.g., Claude, Cursor, Aider) that have direct access to the project repository. These assistants handle implementation planning against the actual codebase and code generation/modification. The system provides them with the relevant architecture documents and plans; they handle reading the code and producing the changes.

## B.9 LLM Integration

- BYO credentials — customers supply their own API keys, stored encrypted per-user in the database
- Token tracking per call, aggregated per node, flow run, and project
- Model and temperature configurable at project, phase, and node levels
- Multiple LLM providers supported behind a common interface
