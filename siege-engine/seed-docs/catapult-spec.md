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

### A.1.2 Folder Mapping

Each leaf boulder corresponds to a folder in the project repository. This gives a direct, deterministic mapping between the document tree and the codebase: a leaf boulder's folder is its territory. This mapping must be explicitly enforced in prompts and generation.

### A.1.3 Root Boulders

At every fan-out level, there is a **root boulder** that owns files not belonging to any fanned-out child. At the system level this is the "system root component," at the component level this is the "component root subcomponent." These handle configuration files, Dockerfiles, shared utilities, and anything else that lives outside the fanned-out folders.

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

Input is a feature description. At each architecture node, produces a plan document analyzing what needs to change, updates the architecture document, then propagates downward to affected leaf boulders where it generates a PR commit. Leaf nodes use the plan from their parent boulder.

### A.2.3 Refactor Flow

Input is a refactoring objective. Same structure as feature request: plan at each architecture node, update the architecture, propagate downward to leaf boulders for PR generation.

### A.2.4 Upward Propagation Flow

Always initiated by the user. Used when new requirements discovered at downstream nodes need to propagate through the rest of the system. Starts at the tree's root and walks downward, but its purpose is to synchronize upstream documentation with changes that originated below. At each fan-out node, determines which children need updates based on the changes being propagated.

### A.2.5 Bug Fix Flow

Input is a PR that fixes a bug (not the bug itself). The system maps changed files back to leaf boulders via the folder mapping (Section A.1.2). From the identified leaf boulders, the flow operates as an upward propagation: walking from each touched leaf up to the project root, updating documentation at each level to reflect what the code change reveals. At fan-out nodes where multiple sibling leaves propagate upward, the system synchronizes their changes into a coherent update to the parent architecture.

## A.3 Phases

Every flow run walks the document DAG in five phases. Each phase has a boulder template defining the processing steps for that phase.

1. **Input Expansion** — Takes raw user input and expands it into a structured requirements document
2. **System Docs** — Produces or updates system-level architecture for the system boulder
3. **Component Docs** — Instantiated once per component boulder; produces or updates component-level architecture
4. **Subcomponent Docs** — Instantiated once per subcomponent boulder; produces or updates subcomponent-level architecture
5. **Leaf Nodes** — Instantiated once per leaf boulder; produces implementation plans and PR commits

### A.3.1 Phase Traversal

A flow run always starts with an input document, expands it into a requirements document, then walks the tree from one particular node out to its furthest descendants. At each node it generates or edits one or more documents as defined by its flow type.

### A.3.2 Propagation

By default, propagation of changes goes **downward**. At fan-out nodes, the system generates a routing document determining which child nodes to visit.

**Upward propagation** goes up to the tree's first ancestor and then downward, with fan-out routing at each level. Upward propagation is always user-initiated and is specifically for ensuring changes found at downstream nodes make it through the rest of the system.

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
- All output documents from ancestor boulders (retrieved via semantic relevance, not concatenated verbatim)
- All ancestor outputs within the same boulder template DAG (included directly)
- The expanded input document (always included if not otherwise present)
- Direct parent outputs are always included in full

Context assembly uses a **strategy pattern** — different flows and phases use different methods for gathering context. Architecture nodes need structural context (parent architecture, sibling summaries). Leaf plan nodes need the parent plan plus current code state. Fan-out routing nodes need summary-level understanding of all children. Upward propagation nodes need what changed below and what exists above.

## A.4 Boulder Templates

Each flow has a boulder template for each phase. A boulder template is itself a DAG of processing nodes within the boulder, defining the constellation of prompts used to generate documents for that system/component/subcomponent.

### A.4.1 Template Pinning

When a flow run is scheduled, it pins to the boulder template versions that exist at schedule time. Template updates made after scheduling do not affect in-progress runs. Template updates are queued with flows — the UI shows the queue at project, boulder, and node levels so users can see what version each run is using and what changes are pending.

### A.4.2 Template Visibility and Editability

All nodes in boulder templates are visible to users. Users can see and understand the full processing pipeline. Users can modify boulder templates: adding, removing, or reordering nodes. This is possible because all node types are surfaced in the UI.

## A.5 Sub-Runs

Flow runs can spawn sub-runs. For example, a refactor sub-run during a scaffolding run, or an upward propagation sub-run during a refactor. Only one run or sub-run may be active at a time per project — sub-runs pause their parent run, execute, and then the parent resumes.

## A.6 Review and Approval

Every document and commit produced by the system goes through review:

1. **AI self-review** — The AI reviews its own output with structured feedback (quality score, recommendation, notes). If revision is recommended, the system automatically regenerates incorporating feedback, up to a configurable loop limit.
2. **Human review** — After AI review, artifacts enter "awaiting review" status. Humans approve or reject with text feedback only (no inline edits). Rejection feedback is incorporated in a subsequent AI revision pass.
3. **CI loop** — For code commits, CI results feed back into the generation loop. CI failure is not a bug fix — it means the system generated incorrect code and should retry with the error output as additional context. This is a first-class concept.

### A.6.1 Auto-Approval

Some node types can be configured for auto-approval, skipping human review. This is configurable per node type, per phase, or per project.

### A.6.2 Review Granularity

Review gates are configurable: per-node, per-phase, leaves-only, or fully automatic. The default should be sensible but the user controls it.

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

## A.9 Git Strategy

- **One commit per leaf node** — Each leaf boulder produces a single commit
- **One PR per flow run** — All leaf commits from a flow run are composed into a single PR, ordered by dependency structure
- **Sub-run commits** contribute to the parent flow's PR
- The system is the sole code shipping mechanism for the project (aside from bug fix PRs which are the input, not the output). Every project is assumed to be a monorepo.

## A.10 Document Versioning

- All artifacts are versioned. Each generation or revision produces a new version.
- Event sourcing provides a complete audit trail of every state change.
- Users can revert to any previous version. Reversion appends new events (no destructive history changes).
- Each completed run produces a git commit checkpoint.

## A.11 Prompt System

- Each processing node type has a built-in prompt template with: system message, output format instructions, context assembly template, and revision instructions.
- Users can override any prompt field per stage per project.
- Model and temperature are configurable at three levels: project default, per-phase default, and per-node override. Defaults propagate downward.

## A.12 Credentials and Token Tracking

- The service is **BYO LLM credentials** — customers supply their own API keys through the application, not environment variables. Credentials are stored per-user.
- Token usage is tracked per node, per flow run, and per project. Users can see how many tokens each generation step consumed.
- Cost projection is deferred to a future version, but the tracking infrastructure is in place from day one.

## A.13 Real-Time Updates

- All connected clients receive live updates when artifacts are generated, statuses change, or flows progress.
- DAG visualizations, status indicators, and artifact viewers update in real-time.

## A.14 Auth and Multi-User Access

- Role-based access control: admin (full control), member (run flows, review, configure), viewer (read-only, can comment).
- Invite-based onboarding with time-limited tokens.
- Per-user LLM credential storage.
- Per-user git credential storage for push/PR operations.

## A.15 Multi-Project Support

- Multiple independent projects, each with its own repository, document DAG, pipeline configuration, and event history.
- One active flow run per project at a time; different projects run concurrently.

## A.16 Bootstrap Flow

- A one-time self-bootstrapping flow for onboarding existing codebases.
- Takes as input: existing documents matching the scaffolding flow's output shape, plus an existing codebase.
- Reconstructs the boulder hierarchy and dependency DAG from the provided documents, aligns codebase files to leaf boulders via folder mapping.
- Destructive to existing project state; can only run once or on a fresh project.

## A.17 AI Coding Assistant Integration

The coding portion of leaf boulder execution (plan creation and PR generation) is delegated to an AI coding assistant. The assistant has tools to read, navigate, and understand the current codebase directly — no separate code parsing or AST indexing is needed. The assistant works up implementation plans since it already has the tools to see the code in context. The document tree provides the "what needs to change" and the coding assistant handles the "how to change it" against the actual code.

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

## B.4 Oban

Background job processing for work that doesn't fit Commanded's event-driven model: LLM API calls, git operations, CI polling, credential refresh, and other side-effectful operations that need retries, scheduling, and observability. Oban jobs are triggered by Commanded events and emit commands back into the event-sourced domain on completion.

## B.5 pgvector

Vector embeddings stored in PostgreSQL via pgvector for semantic retrieval during context assembly. Document chunks are embedded and indexed so that deep nodes can retrieve relevant ancestor context by semantic similarity rather than consuming entire documents. The retrieval strategy varies by flow and phase (Section A.3.5).

## B.6 Gitea (API-only sidecar)

A Gitea instance runs as an API-only sidecar — no separate git UI, the application provides its own. Gitea handles the git hosting, branch management, PR mechanics, and merge conflict resolution behind an API. This offloads complex git edge cases (merge conflicts, branch composition, PR state management) to a purpose-built tool rather than reimplementing them. Combined with the one-run-at-a-time constraint and folder-per-leaf-boulder mapping, merge conflicts should be nearly eliminated.

## B.7 Phoenix / LiveView

Web framework and real-time UI layer. Phoenix Channels provide WebSocket-based live updates. LiveView powers the interactive DAG visualizations, artifact viewers, review interfaces, and template editors. No separate frontend build — the UI is server-rendered with client-side interactivity via LiveView.

## B.8 AI Coding Assistants

Leaf boulder code generation is delegated to AI coding assistants (e.g., Claude, Cursor, Aider) that have direct access to the project repository. These assistants handle implementation planning against the actual codebase and code generation/modification. The system provides them with the relevant architecture documents and plans; they handle reading the code and producing the changes.

## B.9 LLM Integration

- BYO credentials — customers supply their own API keys, stored encrypted per-user in the database
- Token tracking per call, aggregated per node, flow run, and project
- Model and temperature configurable at project, phase, and node levels
- Multiple LLM providers supported behind a common interface
