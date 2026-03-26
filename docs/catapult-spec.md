# Catapult - System Specification

## Part A: Requirements

### 1. Core Concepts

Catapult is an AI-powered software development pipeline that generates and
maintains a full software system from natural-language inputs. It operates on a
**boulder tree** -- a hierarchical structure of document groups (boulders) that
mirrors the decomposition of a system into components and subcomponents.

**Boulder**: A DAG of document nodes representing the artifacts for a single
system, component, or subcomponent. A boulder template defines which documents
are produced and their dependency relationships within the boulder.

**Boulder Tree**: The hierarchical nesting of boulders. The tree has exactly
three levels of branching: system, component, and subcomponent. Subcomponents
are terminal -- they cannot fan out into further subcomponents. This two-layer
branching limit (system→component, component→subcomponent) bounds tree depth
and keeps context manageable.

**Leaf Boulder**: A terminal, single-use boulder that produces at minimum a
plan and a commit. Leaf boulders may be children of system, component, or
subcomponent boulders depending on where the tree stops expanding.

**Flow**: A parameterized pipeline execution that walks the boulder tree
according to a specific strategy (scaffolding, upward propagation, refactor,
feature request, or bug fix). A flow run produces one pull request containing
commits from all of its leaf boulders.

**Phase**: A tier in the boulder tree. Every flow walks through up to five
phases: input expansion, system docs, component docs, subcomponent docs, and
leaf nodes.

### 2. Flow Types

#### 2.1 Scaffolding Flow

The scaffolding flow creates a system from scratch or expands an existing
system into new areas.

- Accepts an input document describing what should be built.
- Expands the input into a requirements document.
- At each phase, generates the boulder's documents using the scaffolding
  template for that phase.
- At each system and component node, produces an architecture document and a
  fan-out node.
- At subcomponent nodes, produces an architecture document only (no further
  fan-out -- subcomponents are terminal).
- Fan-out nodes produce a document and structured output deciding whether each
  child needs further expansion. Children that do not need expansion get a leaf
  boulder generated for them instead.

#### 2.2 Upward Propagation Flow

Upward propagation captures requirements discovered at downstream nodes and
ensures those changes are reflected across the entire system.

- Always initiated by a user, never automatically.
- Accepts an input document describing the new requirements or changes found
  downstream.
- Navigates upward to the tree's root ancestor.
- From the root, propagates downward through every fan-out node, similarly to
  normal downward propagation but visiting the full tree.
- At each fan-out node, generates a routing document determining which children
  are affected and should be visited.

#### 2.3 Refactor Flow

The refactor flow modifies existing architecture and propagates structural
changes to implementation.

- Accepts an input document describing the desired refactor.
- At each architecture node, generates a plan, then updates the architecture
  document.
- Propagates downward to leaf nodes, where each leaf generates a commit using
  the plan from its parent architecture node.

#### 2.4 Feature Request Flow

The feature request flow adds new capabilities to an existing system.

- Accepts an input document describing the feature.
- At each architecture node, generates a plan, then updates the architecture
  document.
- Propagates downward to leaf nodes, where each leaf generates a commit using
  the plan from its parent architecture node.
- May trigger fan-out at nodes that need new children to support the feature.

#### 2.5 Bug Fix Flow

The bug fix flow starts from a merged PR that fixes a bug and propagates
documentation updates upward through the system.

- Accepts a pull request (not a bug report) that fixes a bug.
- Identifies all leaf boulders touched by the PR's changes.
- From each touched leaf, initiates an upward propagation to the project root.
- At each fan-out node encountered during upward traversal, synchronizes
  changes across sibling branches -- ensuring that documentation at fan-out
  points reflects the combined impact of the fix across all affected children.
- Updates documentation at each visited node as necessary to reflect the fix.
- The source of truth is the code change, not a requirements document. Each
  visited node's documentation is reconciled against the actual diff.

### 3. Pipeline Algorithm

#### 3.1 Flow Execution

A flow run always begins with an input document and proceeds through phases:

1. **Input Expansion**: The input document is expanded into a structured
   requirements document.
2. **System Docs**: The system-level boulder is visited. Documents are generated
   or updated according to the flow's boulder template for this phase.
3. **Component Docs**: Each affected component boulder is visited.
4. **Subcomponent Docs**: Each affected subcomponent boulder is visited.
5. **Leaf Nodes**: Terminal boulders produce plans and commits.

At each phase, the flow applies its boulder template for that tier. The
template is itself a DAG -- nodes within it execute in dependency order.

#### 3.2 Propagation

By default, propagation flows downward from the starting node to its furthest
descendants. At fan-out nodes, the system generates a routing document that
determines which children to visit.

The system must support both:

- **Downward propagation**: The default. Changes flow from parent to children.
- **Upward propagation**: User-initiated (or triggered by bug fix flows).
  Navigates to the root, then propagates downward through the full tree. At
  fan-out nodes during the downward pass, changes from multiple upward sources
  are synchronized before continuing to children.

#### 3.3 Parallel Execution

Within a phase or within a boulder, nodes that do not depend on each other and
whose parent nodes have completed generation may execute in parallel.

The system should maximize parallelism while respecting the dependency ordering
defined by the boulder template DAG and the boulder tree structure.

#### 3.4 Sub-runs

A flow run may spawn sub-runs. For example:

- A scaffolding run may trigger a refactor sub-run if the generated architecture
  conflicts with existing work.
- A refactor run may trigger upward propagation if the refactor reveals
  requirements that affect sibling components.

Sub-runs execute within the context of their parent run. The system must track
the parent-child relationship between runs and sub-runs.

#### 3.5 Node Input Assembly

The input to any document node is the union of:

1. All output documents from ancestor boulders (parent, grandparent, etc. in
   the boulder tree).
2. All completed ancestor outputs within the same boulder (per the boulder's
   internal DAG).
3. The expanded input document, if not already included via (1) or (2).

The total context for deep nodes will exceed what can be passed directly to an
LLM. The system must use retrieval-augmented generation (RAG) with a vector
database to assemble node inputs. Documents are indexed as embeddings, and
node input assembly retrieves the most relevant chunks from ancestor outputs
rather than concatenating full documents. The expanded input document and
direct parent outputs should always be included in full; more distant ancestors
are retrieved by semantic relevance.

### 4. Boulder Templates

Each flow defines a boulder template for each phase. A boulder template
specifies:

- The set of document nodes to produce.
- The dependency relationships between those nodes (forming a DAG).
- The prompts or prompt strategies used to generate each document.

Boulder templates are themselves DAGs within the boulder tree.

#### 4.1 Template Versioning and Scheduling

Template changes are versioned and queued alongside flows. When a flow is
scheduled, it captures the current template versions at that moment. The flow
uses those pinned template versions throughout its entire execution, regardless
of any template updates that occur after scheduling.

This means:

- Template updates never affect in-progress or already-queued flows.
- The effect of a template change is predictable: it applies to the next flow
  scheduled after the change.
- The UI should clearly show the queue at project, boulder, and node levels,
  including which template version each queued flow will use.

### 5. Fan-out and Termination

Fan-out nodes appear at system and component phases during scaffolding. A
fan-out node:

- Generates a document analyzing the parent's architecture.
- Produces structured output deciding for each potential child whether to:
  - Expand (create a child boulder at the next phase), or
  - Terminate (generate a leaf boulder instead).

The tree has a hard depth limit of two branching layers:

- System → Components (first fan-out)
- Components → Subcomponents (second fan-out)
- Subcomponents do not fan out. They either produce their documents directly
  or generate leaf boulders.

This guarantees termination without requiring runtime depth checks.

### 6. Human Review

The system must support human review gates at configurable points in the
pipeline. At minimum:

- Users must be able to review and approve/reject the expanded input document
  before the flow proceeds into the boulder tree.
- Users must be able to review and approve/reject documents at any boulder node
  before dependent nodes execute.
- Users must be able to review leaf commits and the overall PR before they are
  finalized.

The system should support configurable review policies: review everything,
review only at phase boundaries, review only at leaves, or fully automatic.

#### 6.1 Run Restart Semantics

When a user rejects a document or requests changes, the system must provide
clear semantics for restarting or retrying portions of a flow:

- **Node-level restart**: Re-execute a single node with the same or modified
  inputs. Downstream nodes that depended on the old output are invalidated.
- **Phase-level restart**: Re-execute all nodes in a phase. Useful when a
  fan-out decision was wrong and the user wants to restructure.
- **Flow-level restart**: Restart the entire flow from input expansion or from
  a specific phase. Previously completed work is discarded or archived.
- **Partial retry**: Re-execute only the failed or rejected nodes within a
  phase, keeping approved siblings intact.

The system must clearly communicate what will be invalidated by each restart
option. Invalidated nodes should be marked but their previous outputs preserved
for reference (not deleted).

### 7. Document Versioning

Documents are edited by multiple flows over time. The system must:

- Track the version history of every document.
- Record which flow run and which node produced each version.
- Support diffing between versions.
- Serialize concurrent access using pessimistic locking (see Section 8).

### 8. Concurrency and Locking

The system uses **pessimistic locking** for concurrent access to boulder tree
nodes. When a flow (or sub-run) needs to visit a node, it acquires a lock on
that node before proceeding. The lock is held until the flow completes its
work on that node.

Specific rules:

- A flow must acquire a lock on a document node before reading or writing it.
- If a node is already locked by another flow, the requesting flow queues
  behind it. The system does not attempt concurrent edits or optimistic
  conflict resolution.
- Sub-runs acquire locks independently. If a sub-run needs a node locked by
  its parent run, this is a deadlock -- the system must detect and surface
  this to the user rather than silently hanging.
- The UI should show lock status on nodes so users can see what is blocked
  and why.
- Lock granularity is at the document node level, not the boulder level. Two
  flows can work on different nodes within the same boulder concurrently.

### 9. Resumability and Recoverability

If a flow run fails partway through (LLM error, timeout, infrastructure
failure), the system must be able to resume the flow from the point of failure
without re-executing successfully completed nodes.

- Completed nodes are recorded in the event log. On resume, the system
  replays the flow's event history to determine which nodes are done and
  which remain.
- Failed nodes can be retried individually without restarting the flow.
- The system must release locks held by failed flows so they do not block
  other work indefinitely. Lock release on failure should be automatic with
  a configurable timeout.
- The UI should clearly distinguish between flows that are running, paused
  (awaiting review), failed (awaiting retry), and completed.

### 10. Git Integration

The system must integrate with git for leaf node output:

- Each leaf boulder produces one **commit** against the target repository.
- Each flow run produces one **pull request** containing all commits from its
  leaf boulders.
- Commits within a PR are ordered to reflect the dependency structure of the
  boulder tree (parent boulders' leaves commit before child boulders' leaves
  where dependencies exist).
- Bug fix flows accept an existing PR as input and must be able to read its
  diff and associated context.
- Sub-runs contribute their commits to the parent flow's PR.

### 11. Observability

Users must be able to:

- See the current state of the boulder tree (which nodes exist, their status,
  their documents, their lock status).
- See the progress of an active flow run (which phase, which nodes are
  executing, which are queued, which are complete, which are blocked by locks).
- See the flow and template queue at project, boulder, and node level.
- See the history of flow runs and their outcomes.
- Navigate from any document to the flow run and node that produced it.

### 12. Input Document Lifecycle

Input documents are the entry point for every flow. The system must:

- Accept input documents in natural language (free-form text).
- Support different input types per flow (text descriptions for scaffolding/
  features/refactors, PR references for bug fixes).
- Preserve the original input alongside its expanded form.
- Allow users to edit the expanded requirements before the flow proceeds.

### 13. Multi-Project Support

The system should support multiple independent projects, each with its own
boulder tree, document history, and flow runs. Users should be able to switch
between projects.

### 14. Auditability

Every action in the system should be traceable:

- Every document generation, edit, approval, and rejection must be recorded
  as an event.
- Every flow run, sub-run, and node execution must be logged with inputs,
  outputs, and timing.
- The event history must be immutable -- events are appended, never modified
  or deleted.
- The system should be able to reconstruct the state of any document or boulder
  at any point in time from the event log.

---

## Part B: Architecture

### 1. Language and Runtime

**Elixir on BEAM** -- The primary application language. The BEAM VM provides
lightweight processes, fault-tolerant supervision trees, and built-in
distribution primitives. Elixir's process model maps naturally to parallel node
execution within boulders and concurrent flow runs.

### 2. CQRS and Event Sourcing

**Commanded** -- An Elixir framework for Command Query Responsibility
Segregation (CQRS) and Event Sourcing. Provides:

- **Aggregates** for modeling domain entities (flow runs, boulders, document
  nodes) with command validation and event emission.
- **Process Managers** for orchestrating multi-step flows across aggregates
  (e.g., walking the boulder tree, coordinating sub-runs, managing lock
  acquisition and queuing).
- **Event Handlers** for building read-model projections and triggering
  side effects.
- **Middleware** for cross-cutting concerns (audit logging, authorization,
  lock enforcement).

All state changes flow through commands and events. The event log is the
system's source of truth, satisfying the auditability requirement and enabling
full state reconstruction.

### 3. Database

**PostgreSQL** -- The primary data store, serving three roles:

- **Event Store**: Commanded's Postgres-backed event store for append-only
  event persistence.
- **Read Models / Projections**: Materialized views of current state, built
  by event handlers projecting from the event stream. Used for queries, UI,
  and API responses.
- **General Storage**: User accounts, project metadata, boulder templates,
  template version history, and other reference data.

### 4. Vector Database

A vector database (e.g., pgvector as a PostgreSQL extension, or a dedicated
store) for RAG-based node input assembly:

- Documents and document chunks are embedded and indexed as vectors.
- Node input assembly queries the vector store to retrieve the most relevant
  context from ancestor documents rather than passing full document contents.
- Embeddings are updated when documents are generated or modified.

### 5. Background Job Processing

**Oban (with Oban Pro)** -- Postgres-backed job processing for work that
doesn't belong in the event-sourced command flow:

- **LLM Calls**: Queued as Oban jobs with retries, timeouts, and rate limiting.
- **Embedding Generation**: Vector indexing of newly generated documents.
- **PR Generation**: Git operations and GitHub API calls.
- **Parallel Node Execution**: Oban's concurrency controls manage how many
  nodes execute simultaneously.
- **Workflow Orchestration**: Oban Pro's workflow features for composing
  multi-step job sequences within a boulder.
- **Batch Operations**: Fan-out node processing where multiple children need
  generation.

Oban complements Commanded: Commanded handles state transitions and event flow,
Oban handles the actual work execution with backpressure and retry semantics.

### 6. Web Framework

**Phoenix / Phoenix LiveView** -- Web framework and real-time UI:

- **LiveView**: Server-rendered interactive UI with WebSocket-based updates.
  Boulder tree visualization, flow progress, queue views, and document editing
  update in real time without client-side framework complexity.
- **Phoenix Channels**: WebSocket pub/sub for broadcasting flow progress,
  node status changes, and lock state updates.
- **REST/JSON API**: For programmatic access and integrations.

### 7. LLM Integration

An Elixir client library for calling LLM APIs (Anthropic Claude). Wrapped
behind an internal abstraction so the specific provider can change. LLM calls
are dispatched as Oban jobs, not made inline during command processing.

### 8. Git Integration

**Git CLI / GitHub API** -- For leaf node commit generation and bug fix PR
ingestion. Operations run as Oban jobs. Each leaf boulder produces a commit;
the flow run composes these into a single PR. The system maintains working
copies or uses the GitHub API directly for file operations.

### 9. Authentication and Authorization

**Standard Phoenix auth** -- User accounts, sessions, and role-based access
control. Not event-sourced -- managed through conventional Ecto/Postgres
patterns. Authorization middleware in Commanded gates command execution.

### 10. Deployment

**Fly.io** -- Application hosting with:

- Single-region deployment initially, expandable to multi-region.
- Postgres managed database.
- Machine suspend/resume for cost management during low-traffic periods.

### 11. High-Level Data Flow

```
User Input
    |
    v
[StartFlow Command] --> FlowRun Aggregate
    |                       |
    | (event)               | (pins template versions,
    v                       |  emits FlowScheduled)
    |                       v
    |                   Event Handler:
    |                   Update queue projection
    v
Oban Job:
Expand Input (LLM)
    |
    | (result)
    v
[InputExpanded Command] --> FlowRun Aggregate
    |                           |
    | (event)                   | (emits InputExpanded,
    v                           |  awaits review if configured)
    |                           v
    |                       Event Handler:
    |                       Update UI projection
    v
Process Manager: BoulderTreeWalker
    |
    | (acquires node lock)
    | (determines next nodes from template DAG)
    v
[GenerateDocument Command] --> Boulder Aggregate
    |                              |
    | (event)                      | (emits GenerationRequested)
    v                              v
Oban Job:                     Event Handler:
Assemble context (RAG) →      Update node status,
Call LLM →                    show lock holders
Return result
    |
    | (result)
    v
[DocumentGenerated Command] --> Boulder Aggregate
    |                               |
    | (event)                       | (emits DocumentGenerated)
    v                               v
Oban Job:                      Event Handler:
Embed document chunks →        Project document to read model,
Index in vector store          release node lock, notify UI
    |
    v
Process Manager: BoulderTreeWalker
    |
    | (check boulder DAG: more nodes? next phase? fan-out?)
    | (at leaf: generate commit via Oban job)
    | (all leaves done: create PR via Oban job)
    v
[FlowCompleted Command] --> FlowRun Aggregate
```

The cycle repeats -- process managers react to events and issue the next
commands, Oban jobs handle the actual LLM/git/embedding work, event handlers
keep projections current for the UI and queue views.
