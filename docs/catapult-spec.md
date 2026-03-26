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

**Boulder Tree**: The hierarchical nesting of boulders. The root is the system
boulder, which fans out into component boulders, which fan out into
subcomponent boulders, which terminate in leaf boulders.

**Leaf Boulder**: A terminal, single-use boulder that produces at minimum a
plan and a pull request. Leaf boulders may be children of system, component, or
subcomponent boulders depending on where the tree stops expanding.

**Flow**: A parameterized pipeline execution that walks the boulder tree
according to a specific strategy (scaffolding, upward propagation, refactor,
feature request, or bug fix).

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
  fan-out).
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
- Propagates downward to leaf nodes, where each leaf generates a PR using the
  plan from its parent architecture node.

#### 2.4 Feature Request Flow

The feature request flow adds new capabilities to an existing system.

- Accepts an input document describing the feature.
- At each architecture node, generates a plan, then updates the architecture
  document.
- Propagates downward to leaf nodes, where each leaf generates a PR using the
  plan from its parent architecture node.
- May trigger fan-out at nodes that need new children to support the feature.

#### 2.5 Bug Fix Flow

The bug fix flow works in reverse compared to other flows -- it starts from
code and updates documentation.

- Accepts a pull request (not a bug report) that fixes a bug.
- Updates documentation as necessary to reflect the fix.
- Propagation direction and strategy may differ from other flows since the
  source of truth is the code change, not a requirements document.

### 3. Pipeline Algorithm

#### 3.1 Flow Execution

A flow run always begins with an input document and proceeds through phases:

1. **Input Expansion**: The input document is expanded into a structured
   requirements document.
2. **System Docs**: The system-level boulder is visited. Documents are generated
   or updated according to the flow's boulder template for this phase.
3. **Component Docs**: Each affected component boulder is visited.
4. **Subcomponent Docs**: Each affected subcomponent boulder is visited.
5. **Leaf Nodes**: Terminal boulders produce plans and PRs.

At each phase, the flow applies its boulder template for that tier. The
template is itself a DAG -- nodes within it execute in dependency order.

#### 3.2 Propagation

By default, propagation flows downward from the starting node to its furthest
descendants. At fan-out nodes, the system generates a routing document that
determines which children to visit.

The system must support both:

- **Downward propagation**: The default. Changes flow from parent to children.
- **Upward propagation**: User-initiated. Navigates to the root, then
  propagates downward through the full tree.

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

The system must have a strategy for managing input size. As documents accumulate
through tree depth, the total input to deep nodes may exceed practical limits.
The system should support summarization, selective inclusion, or other
strategies to keep node inputs within usable bounds without losing critical
context.

### 4. Boulder Templates

Each flow defines a boulder template for each phase. A boulder template
specifies:

- The set of document nodes to produce.
- The dependency relationships between those nodes (forming a DAG).
- The prompts or prompt strategies used to generate each document.

Boulder templates are themselves DAGs within the boulder tree. Changes to
templates should be versioned. A flow run should use a consistent template
version throughout its execution -- it should not pick up template changes
mid-run.

### 5. Fan-out and Termination

Fan-out nodes appear at system and component phases during scaffolding. A
fan-out node:

- Generates a document analyzing the parent's architecture.
- Produces structured output deciding for each potential child whether to:
  - Expand (create a child boulder at the next phase), or
  - Terminate (generate a leaf boulder instead).

The system must enforce termination guarantees. Fan-out should not recurse
unboundedly. The system should define a maximum tree depth or restrict fan-out
to specific phases (e.g., subcomponent nodes cannot fan out further -- they
only produce architectures or leaves).

### 6. Human Review

The system must support human review gates at configurable points in the
pipeline. At minimum:

- Users must be able to review and approve/reject the expanded input document
  before the flow proceeds into the boulder tree.
- Users must be able to review and approve/reject documents at any boulder node
  before dependent nodes execute.
- Users must be able to review leaf PRs before they are finalized.

The system should support configurable review policies: review everything,
review only at phase boundaries, review only at leaves, or fully automatic.

### 7. Document Versioning

Documents are edited by multiple flows over time. The system must:

- Track the version history of every document.
- Record which flow run and which node produced each version.
- Support diffing between versions.
- Handle the case where two flows want to edit the same document. The system
  must either serialize access (lock the document for the duration of the
  editing flow) or detect and surface conflicts for human resolution.

### 8. Concurrency and Locking

Multiple flows may target overlapping regions of the boulder tree. The system
must define a concurrency model:

- Whether concurrent flows can visit the same boulder simultaneously.
- How sub-runs interact with the parent run's active nodes.
- What happens when a queued flow targets a node that is locked by another
  flow.

At minimum, the system must prevent two flows from editing the same document
node at the same time. The strategy (optimistic locking with conflict
detection, pessimistic locking with queuing, or node-level mutual exclusion)
is an implementation decision, but the requirement is that concurrent edits
do not silently clobber each other.

### 9. Resumability

If a flow run fails partway through (LLM error, timeout, infrastructure
failure), the system must be able to resume the flow from the point of failure
without re-executing successfully completed nodes.

Completed nodes should be idempotent on re-run -- if a node is re-executed, it
should produce the same result or the system should detect that it has already
been completed and skip it.

### 10. Git Integration

The system must integrate with git for leaf node output:

- Leaf boulders produce pull requests against the target repository.
- The system must define a branching strategy: one branch per leaf, per flow
  run, or per some other grouping.
- PRs from the same flow run should be composable -- the system should support
  merging multiple leaf outputs into a coherent set of changes.
- Bug fix flows accept an existing PR as input and must be able to read its
  diff and associated context.

### 11. Observability

Users must be able to:

- See the current state of the boulder tree (which nodes exist, their status,
  their documents).
- See the progress of an active flow run (which phase, which nodes are
  executing, which are queued, which are complete).
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
  (e.g., walking the boulder tree, coordinating sub-runs).
- **Event Handlers** for building read-model projections and triggering
  side effects.
- **Middleware** for cross-cutting concerns (audit logging, authorization).

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
  and other reference data.

### 4. Background Job Processing

**Oban (with Oban Pro)** -- Postgres-backed job processing for work that
doesn't belong in the event-sourced command flow:

- **LLM Calls**: Queued as Oban jobs with retries, timeouts, and rate limiting.
- **PR Generation**: Git operations and GitHub API calls.
- **Parallel Node Execution**: Oban's concurrency controls manage how many
  nodes execute simultaneously.
- **Workflow Orchestration**: Oban Pro's workflow features for composing
  multi-step job sequences within a boulder.
- **Batch Operations**: Fan-out node processing where multiple children need
  generation.

Oban complements Commanded: Commanded handles state transitions and event flow,
Oban handles the actual work execution with backpressure and retry semantics.

### 5. Web Framework

**Phoenix / Phoenix LiveView** -- Web framework and real-time UI:

- **LiveView**: Server-rendered interactive UI with WebSocket-based updates.
  Boulder tree visualization, flow progress, and document editing update in
  real time without client-side framework complexity.
- **Phoenix Channels**: WebSocket pub/sub for broadcasting flow progress and
  node status changes.
- **REST/JSON API**: For programmatic access and integrations.

### 6. LLM Integration

An Elixir client library for calling LLM APIs (Anthropic Claude). Wrapped
behind an internal abstraction so the specific provider can change. LLM calls
are dispatched as Oban jobs, not made inline during command processing.

### 7. Git Integration

**Git CLI / GitHub API** -- For leaf node PR generation and bug fix PR
ingestion. Operations run as Oban jobs. The system maintains working copies
or uses the GitHub API directly for file operations.

### 8. Authentication and Authorization

**Standard Phoenix auth** -- User accounts, sessions, and role-based access
control. Not event-sourced -- managed through conventional Ecto/Postgres
patterns. Authorization middleware in Commanded gates command execution.

### 9. Deployment

**Fly.io** -- Application hosting with:

- Single-region deployment initially, expandable to multi-region.
- Postgres managed database.
- Machine suspend/resume for cost management during low-traffic periods.

### 10. High-Level Data Flow

```
User Input
    |
    v
[Input Command] --> Commanded Aggregate (FlowRun)
    |                    |
    | (event)            | (event: FlowStarted)
    v                    v
Oban Job:           Event Handler:
Expand Input        Project to read model
    |
    | (result)
    v
[ExpandedInputReceived Command] --> FlowRun Aggregate
    |                                    |
    | (event)                            |
    v                                    v
Process Manager:                    Event Handler:
BoulderTreeWalker                   Update UI projection
    |
    | (determines next nodes)
    v
[GenerateDocument Command] --> Boulder Aggregate
    |                              |
    | (event)                      | (event: GenerationRequested)
    v                              v
Oban Job:                     Event Handler:
Call LLM                      Update node status
    |
    | (result)
    v
[DocumentGenerated Command] --> Boulder Aggregate
    |                               |
    | (event)                       |
    v                               v
Process Manager:               Event Handler:
Check dependencies,            Project document to
trigger next nodes             read model, notify UI
or next phase
```

The cycle repeats -- process managers react to events and issue the next
commands, Oban jobs handle the actual LLM/git work, event handlers keep
projections current for the UI.
