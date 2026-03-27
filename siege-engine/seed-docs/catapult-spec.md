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

Leaf boulders are single-use boulders that produce implementation artifacts. A leaf boulder may be a child of a system, component, or subcomponent boulder. Every leaf boulder produces at minimum test cases (generated as part of the planning prompt), an implementation plan, and a PR commit.

### A.1.2 Repository and Folder Mapping

Each leaf boulder maps to a `{repository, folder}` pair. For v1, all boulders within a project target a single repository (monorepo assumption), but the mapping is structured to support multi-repo projects in the future without a data model change.

Within a repository, each leaf boulder corresponds to a folder — the boulder's territory. This gives a direct, deterministic mapping between the document tree and the codebase. This mapping must be explicitly enforced in prompts and generation.

### A.1.3 Root Boulders

At every fan-out level, there is a **root boulder** that owns files not belonging to any fanned-out child. At the system level this is the "system root component," at the component level this is the "component root subcomponent." The root boulder's intended purpose is build configuration, infrastructure files, and similar cross-cutting concerns, but its contents are not prescribed — different deployments and ecosystems will have different needs.

### A.1.4 Dual DAG Architecture

- **Pipeline DAG**: A directed acyclic graph of processing stages defining the shape of the work — which AI generation steps run, in what order, and with what inputs. The pipeline DAG is a sequence of 5 phases, each containing a configurable boulder template (itself a DAG). When a phase fans out, the boulder template is instantiated once per boulder.
- **Document DAG**: A directed acyclic graph of artifacts (documents and code) produced by the pipeline. Each node is a versioned document with status tracking. Edges represent parent-child relationships and cross-cutting dependency relationships between sibling boulders. Sibling dependency edges carry unified semantics — a dependency from boulder A to boulder B means all three of: (1) B must be generated before A (execution ordering), (2) A's context assembly includes B's output (context input), and (3) changes to B propagate staleness to A (change tracking). These three meanings are intentionally coupled — they must all hold for the design to work, because a dependency that orders execution but doesn't inform context or propagate staleness would create silent drift.
- The pipeline DAG drives generation; the document DAG records results.

## A.2 Flows

The system supports seven flow types. Only one flow run (or sub-run) may be active per project at a time.

### A.2.1 Scaffolding Flow

The default flow. Generates all documents from scratch, walking the full document DAG top-down through every boulder.

- At system and component boulders: produces an architecture document and a fan-out node
- At subcomponent boulders: produces an architecture document only (no further fan-out)
- Fan-out nodes produce a document and structured output deciding whether to decompose into child boulders or generate a leaf boulder
- Leaf boulders produce test cases (as part of the planning prompt), an implementation plan, and a PR commit

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

There are two variants of the bug fix flow, both operating as upward propagation (Section A.2.4):

#### A.2.5.1 Fix and Propagate

Input is a bug report (description of the problem, not a fix). This flow is primarily intended for bugs the AI notices on its own (via proactive chat analysis, A.22.3), so triage is straightforward — the AI coding assistant (A.21) identifies the affected leaf boulders by analyzing the bug against the codebase, then generates a fix at the leaf level and propagates the implications upward through the document tree:

1. At the leaf level: a **diagnosis node** analyzes the bug, then plan and code generation produce the fix
2. At each boulder level during the upward pass, a **diagnosis node** produces a diagnosis document analyzing what the fix reveals about the gap between the documented architecture and reality — why the bug existed, what assumption was wrong, what edge case was missed
3. An **architecture update node** takes the diagnosis and updates the architecture doc accordingly
4. Parent nodes wait for all descendant diagnoses to complete before producing their own, so changes from multiple touched leaves are merged into a single coherent diagnosis at each fan-out node

During the downward pass, fan-out routing identifies sibling subtrees impacted by the diagnosed changes. The diagnosis chain gives reviewers an explicit, approvable interpretation of what the bug means for the system's design at each level.

If the AI fails to produce a working fix after exhausting retries, the bug report is pushed to a bug/issues queue for manual intervention. No documentation propagation occurs — at the point of failure, no docs have been built yet, so nothing is lost. The bug report and diagnosis are preserved in the queue so a human can fix it and then use A.2.5.2 to propagate the documentation changes.

#### A.2.5.2 Propagate Existing Fix

Input is a PR or commit that already contains changes (the code change exists, documentation needs to catch up). The system maps changed files back to leaf boulders via the folder mapping (Section A.1.2). From the identified leaf boulders, the flow operates purely as documentation propagation — no code generation, only diagnosis and architecture updates at each level upward, then routing to affected siblings on the downward pass. This variant handles any code change made outside Catapult: hotfixes, automated dependency version bumps, CI configuration changes, manual edits — any case where the codebase has moved and the document tree needs to reflect reality.

### A.2.6 Restructuring Flow

A specialized flow for structural changes to the boulder tree that go beyond adding/removing individual boulders at a fan-out step: extracting a subcomponent out of one component into another, splitting a component into multiple components, or merging multiple boulders into one. These operations involve moving code between folder territories and rewriting architecture docs at multiple levels simultaneously.

Input is a restructuring objective (e.g., "extract the AuthZ subcomponent from Auth into its own top-level component"). The flow operates as an upward propagation from the affected boulders, but with the additional ability to modify the boulder tree structure at fan-out nodes during the downward pass — creating, removing, and reparenting boulders as needed. All structural modifications pause for mandatory human review. The resulting PR includes the code moves alongside the document updates.

### A.2.7 Refinement Flow

A system-wide regeneration pass that incorporates accumulated deferred feedback (A.6.0.1). Walks the full document DAG top-down, regenerating nodes that have pending feedback. At each node with feedback, the pending comments are included in the prompt context and the node is regenerated.

Nodes without pending feedback are not automatically skipped — regenerated upstream nodes propagate staleness downward through normal dependency tracking, so feedback on a system-level node may cause the entire tree to regenerate as changes cascade. The flow follows standard staleness propagation rules: if a regenerated node's output differs from its previous version, its dependents are marked stale and regenerated in turn. This means a refinement flow with feedback concentrated at the top of the tree may touch every node, while feedback concentrated at leaves may only touch those leaves.

The refinement flow is the natural response to seeing accumulated feedback counters across the tree. It is distinct from scaffolding (which generates from scratch) and from feature request/refactor (which have a specific objective as input). The refinement flow's input is the feedback itself, already distributed across the tree.

## A.3 Phases

Every flow run walks the document DAG in five phases. Each phase has a boulder template defining the processing steps for that phase. Phases correspond directly to tree depth — phase 2 is the system level, phase 3 is the component level, and so on. Downward flows walk phases in order (1→5); upward propagation walks upward through phases then back down, potentially revisiting phases during the downward pass.

1. **Input Expansion** — Takes raw user input and expands it into a structured requirements document (the "expanded input doc")
2. **System Docs** — Produces or updates system-level architecture for the system boulder
3. **Component Docs** — Instantiated once per component boulder; produces or updates component-level architecture
4. **Subcomponent Docs** — Instantiated once per subcomponent boulder; produces or updates subcomponent-level architecture
5. **Leaf Nodes** — Instantiated once per leaf boulder; produces test cases (built into the planning prompt), implementation plans, and PR commits

### A.3.1 Phase Traversal

A flow run always starts with an input document, expands it into a requirements document (the expanded input doc), then walks the tree from one particular node out to its furthest descendants. At each node it generates or edits one or more documents as defined by its flow type.

### A.3.1.1 Input Document Lifecycle

The raw input document (user-provided) never changes. The **expanded input document** (requirements doc produced by phase 1) is simply the root node of the document DAG. It is not a special case — when a flow traverses the tree and reaches it, it is updated like any other node. When a flow walks downward, it starts from it like any other root.

### A.3.2 Propagation

By default, propagation of changes goes **downward**. At fan-out nodes, the system generates a routing document determining which child nodes to visit. Reviewers can **amend routing decisions directly** — adding boulders the AI missed or removing boulders that don't need updates — before approving. When a reviewer amends the routing list, the routing document is regenerated to incorporate the amended list, so that the reasoning reflects the actual routing for future passes. This prevents the AI from repeating the same routing mistake on subsequent flows.

**Upward propagation** is a two-pass algorithm (see Section A.2.4). During the upward pass, changes are collected bottom-up — parent nodes wait for **all** descendants to complete before updating, so inputs are merged and each parent regenerates only once. During the downward pass, fan-out routing identifies additional children impacted by the merged changes. Upward propagation is always user-initiated.

### A.3.3 Fan-Out

Fan-out nodes are conditional — the AI decides whether decomposition is needed based on complexity. When a fan-out node fires, it produces:
- A list of child boulders with names and descriptions
- A dependency DAG among those boulders specifying execution order
- A root boulder for that level (Section A.1.3) to handle files outside fanned-out folders

Fan-out is bounded: subcomponents are the terminal level. The maximum document tree depth is system → component → subcomponent → leaf.

Fan-out is not a one-time operation. In subsequent flows (feature requests, refactors), fan-out steps can **add or remove** boulders from the existing structure. Adding a component to handle a new feature or removing a subcomponent that's been consolidated are both valid fan-out outcomes. All fan-out modifications pause for mandatory human review (A.24.2).

### A.3.4 Parallel Execution Within Phases

Within a phase or within a boulder template DAG, non-dependent nodes whose parent nodes have completed generation can execute in parallel. Independent sibling boulders (no dependency edges between them) can also be processed in parallel.

### A.3.5 Context Assembly

Context assembly uses a **strategy pattern** — different flows, phases, and node types use different methods for gathering context. The context budget is **partitioned by category**, not applied as a single linear queue. Each strategy defines its own budget partitions based on what that node type needs:

- **Architecture nodes** — budget weighted toward structural context: parent architecture (always in full), sibling summaries, expanded input doc. Smaller allocation for semantic retrieval of distant ancestors.
- **Leaf plan nodes** — budget weighted toward the parent plan (always in full) plus current code state. Smaller allocation for ancestor architectures.
- **Fan-out routing nodes** — budget weighted toward summary-level understanding of all children. Parent architecture in full. Minimal distant ancestor context.
- **Upward propagation nodes** — budget split between what changed below (child outputs) and what exists above (parent architecture).

Within each partition, the budget-based approach applies: include full documents nearest-first until the partition's budget is exhausted, then retrieve remaining context via semantic relevance from the vector database. The expanded input document and direct parent outputs are always included in full, drawn from the appropriate partition.

This means shallower nodes get richer direct context (desirable — system-level decisions benefit from full context) while deeper nodes work from more focused, relevant excerpts.

**Future: intelligent context selection.** Documents are intended to store the complete design decision history of the project — they should never be compacted or summarized destructively. For very large or long-lived projects where documents exceed context budgets even with partitioning, a future version will need a context building service that goes beyond vector search to select the most relevant portions of a document for a given prompt (e.g., structural analysis, recency weighting, decision-chain tracing). This is not needed for v1 but should be anticipated in the context assembly interface design.

### A.3.6 Test Case Lifecycle

Test cases are a first-class artifact with a defined lifecycle through the leaf boulder pipeline:

1. **Generation** — Test cases are produced as part of the planning prompt, before code generation begins. The planning step takes the parent plan and the current code state, and produces both an implementation plan and a set of test cases that define the expected behavior.
2. **Plan artifact** — Test cases are included in the plan document as explicit acceptance criteria. Reviewers can approve or reject the test cases independently of the implementation plan.
3. **Code generation** — The code generation step receives both the implementation plan and the test cases. It produces implementation code and test files. The test cases from the plan serve as the specification for what the test files must cover.
4. **AI code review** — The AI code review step checks generated code against the plan's test cases as a concrete checklist: are all specified behaviors tested? Do the tests match the acceptance criteria?
5. **CI validation** — Generated test files are expected to pass in CI as part of the CI loop (A.6.0). CI failure feeds back into the generation loop for retry.

### A.3.7 CI Integration

CI is an external system that validates generated code. The integration model:

- **Configuration** — CI is configured on the target repository as part of the root boulder's responsibility (A.1.3). Catapult does not manage CI configuration directly — the root boulder's code generation sets up CI pipelines as it would any other infrastructure file.
- **Status monitoring** — Catapult monitors PR check status via Gitea webhooks. When CI completes (pass or fail), Gitea emits a webhook that Catapult processes.
- **Failure retry** — CI failure triggers a regeneration cycle: the error output is included as additional context in the next code generation attempt. The number of CI retry cycles is configurable per project, with a default limit. After exhausting retries, the node is marked failed.
- **Optional** — Projects without CI configured skip the CI loop entirely. The flow proceeds directly from AI code review to human review.

## A.4 Boulder Templates

Each flow has a boulder template for each phase. A boulder template is itself a DAG of processing nodes within the boulder, defining the constellation of prompts used to generate documents for that system/component/subcomponent.

### A.4.1 Template Pinning

When a flow run is scheduled, it pins to the boulder template versions that exist at schedule time. Template updates made after scheduling do not affect in-progress runs. Template updates are queued with flows — the UI shows the queue at project, boulder, and node levels so users can see what version each run is using and what changes are pending.

### A.4.2 Template Visibility and Editability

All nodes in boulder templates are visible to users. Users can see and understand the full processing pipeline. Users can modify boulder templates: adding, removing, or reordering nodes. This is possible because all node types are surfaced in the UI.

### A.4.3 Template Bundles

Templates are distributable as **bundles** — packages that combine boulder template DAGs with their prompt configurations into a single installable unit, distributed via git repositories. A bundle represents a complete set of prompts and DAG configurations for a particular tech stack, framework, or workflow style (e.g., "Elixir/Phoenix scaffolding," "React frontend feature request").

**Instance-level defaults**: Each Catapult instance has a bundle library with instance-level default templates. New projects inherit from instance defaults, with per-project overrides. Self-hosted deployments configure their own defaults; managed deployments provide curated defaults per subscription tier.

**Curation and security**: Template bundles are a prompt injection attack surface — a malicious bundle could embed instructions that exfiltrate document content, inject backdoors into generated code, or manipulate the review flow. Bundles must be curated: instance admins explicitly approve bundles before they're available to projects. The system should support bundle signing and provenance tracking so admins can verify the source and integrity of imported bundles.

## A.5 Sub-Runs

Flow runs can spawn sub-runs. For example, a refactor sub-run during a scaffolding run, or an upward propagation sub-run during a refactor. Only one run or sub-run may be active at a time per project — sub-runs pause their parent run, execute, and then the parent resumes.

When a sub-run completes, the parent run resumes and sees the current state of all nodes — including any modifications made by the sub-run. Nodes that the parent run has not yet processed will simply receive updated context reflecting the sub-run's changes. This is the intended mechanism for handling mid-flow discoveries: if reviewing a component reveals a missing upstream requirement, the user kicks off an upward propagation sub-run, it modifies the relevant upstream nodes, and when the parent resumes, all remaining unprocessed nodes pick up the new context naturally.

## A.6 Review and Approval

Every document and commit produced by the system goes through review. The system provides two review UIs — one for **documents** (markdown rendering, version diffs, feedback panel) and one for **code** (diff view, inline comments, CI status) — but both follow the same underlying status model and workflow.

### A.6.0 Review Paths

**Document artifacts** follow the full review chain:
1. **AI self-review** — The AI reviews its own output with structured feedback (quality score, recommendation, notes). If revision is recommended, the system automatically regenerates incorporating feedback, up to a configurable loop limit.
2. **Human review** — After AI review, artifacts enter "awaiting review" status. Humans review with **inline comments** (tied to specific locations in the document) and **summary feedback** (overall assessment). Inline comments let reviewers anchor feedback to exactly where the problem is ("this JWT assumption contradicts the session decision in A.3"); summary feedback captures cross-cutting concerns. Rejection feedback — both inline and summary — is incorporated in a subsequent AI revision pass. Location-anchored feedback gives the AI much better signal about what to change than unstructured text alone.

**Code artifacts** (leaf boulder PRs) follow a parallel path:
1. **AI code review** — The AI reviews generated code via Gitea's PR review API, posting inline comments tied to file paths and line numbers.
2. **CI loop** — CI results feed back into the generation loop. CI failure is not a bug fix — it means the system generated incorrect code and should retry with the error output as additional context. This is a first-class concept, not an edge case.
3. **Human code review** — After AI review and CI pass, the PR enters "awaiting review" for human review via Catapult's code review UI. Code review uses the same inline comments plus summary feedback model as document review.

### A.6.0.1 Deferred Feedback

Users can leave inline comments and summary feedback on **any node at any time**, not just nodes currently awaiting review. This feedback accumulates as pending and is automatically included in the prompt context the next time that node is regenerated by any flow. This is the lightweight alternative to upward propagation — when working deep in the tree reveals something that an upstream node should incorporate, the user leaves a comment on the upstream node rather than initiating a full flow. Multiple deferred comments can accumulate across multiple nodes from multiple users. Deferred feedback does not trigger regeneration on its own; it waits until the node is next touched by a flow.

**Comment lifecycle**: All comments — review feedback, inline comments, and deferred feedback — can be edited or deleted by their author after posting. Edits and deletions are recorded in the event log (the original content is preserved in history, not destroyed). Comments that have already been consumed by a regeneration pass are marked as such; deleting a consumed comment does not undo the regeneration it influenced. Pending (unconsumed) comments can be freely edited or deleted before the next regeneration picks them up.

**Feedback visibility**: Each node in the DAG visualization displays a pending feedback counter (badge). Counters roll up — a component shows the sum of its own pending feedback plus all its children's. This gives users an at-a-glance view of where feedback has accumulated across the tree, signaling when a refinement flow (A.2.7) is warranted.

### A.6.1 Auto-Approval

Some node types can be configured for auto-approval, skipping human review. This is configurable per node type, per phase, or per project.

### A.6.2 Review Assignment and Team Workflow

#### Boulder Ownership

Each component and subcomponent boulder has an **owner** — the team member who is the default reviewer for everything in that subtree (architecture docs, plans, and code). System-level artifacts default to the project lead or admin.

**Fan-out is the natural assignment point.** Fan-out stages already pause for human review (A.24.2). When the reviewer approves the decomposition into child boulders, they also assign ownership of each child. Ownership is part of the fan-out approval, not a separate step.

#### Review Type Routing

Reviews route to the boulder owner by default, with optional additional reviewers by artifact type:

- **Architecture docs** → boulder owner + optionally a designated architect role
- **Plans** → boulder owner
- **Fan-out decisions** → parent boulder owner (the person who owns the level above decides the decomposition)
- **Code PRs** → boulder owner + optionally any team member with relevant domain expertise

A second reviewer can be optionally required per artifact type via project configuration.

#### Notifications

Reviews are the pipeline's bottleneck. Notifications must be batched — "You have 4 architecture docs ready for review in the Authentication component" is one notification, not four. Channels: in-app (LiveView push) at minimum, with webhook support (Slack/Teams/email) configurable per user.

Each user has a **review queue**: a unified view of all artifacts awaiting their review across all projects, with age and priority indicators.

#### Review SLA and Escalation

Configurable review timeout per project (e.g., 24 hours, 48 hours):

1. After timeout: reminder notification to the assigned reviewer
2. After second timeout: escalate to the parent boulder owner or project admin
3. Optionally: auto-approve with a flag ("auto-approved due to timeout — flagged for post-hoc review"). Configurable, off by default.

#### Delegation

Owners can:
- Reassign a specific review to another team member
- Delegate their entire boulder to someone else (temporary or permanent)
- Split ownership within their subtree (e.g., "I own this component but delegate the database subcomponent to Bob")

### A.6.3 Review Cadence and Granularity

Review gates are configurable: per-node, per-phase, leaves-only, or fully automatic. The default should be sensible but the user controls it.

The intended review workflow is **batched**: the flow produces N documents, then pauses for human review of that batch. The reviewer reads and leaves feedback on some or all documents. Rejected documents and their downstream dependents are then regenerated as a sub-run incorporating the feedback. Once the sub-run completes, the flow resumes and produces the next batch of M documents. This produce-review-regenerate cycle repeats through the flow.

### A.6.4 Restart Semantics

Flow runs support four restart granularities:

- **Node-level** — Regenerate a single node's output; downstream nodes are marked stale
- **Phase-level** — Restart an entire phase; all nodes in that phase are regenerated
- **Flow-level** — Restart the entire flow from input expansion
- **Partial retry** — Retry only failed/rejected nodes within a phase, leaving approved nodes intact

Each restart option clearly communicates what gets invalidated.

### A.6.5 Status Chain

**Document artifacts:**
pending → generating → ai_reviewing → awaiting_review → approved / rejected / stale

**Code artifacts:**
pending → generating → ai_reviewing → ci_validating → awaiting_review → approved / rejected / stale

The `ci_validating` status is specific to code artifacts and represents the CI loop (A.3.7). Nodes cycle between `ci_validating` and `generating` on CI failure until the retry limit is reached. Projects without CI skip `ci_validating` entirely.

Rejecting an artifact propagates staleness downstream.

## A.7 Flow Lobby

Proposed flows do not execute immediately. They enter a **lobby** where they can be reviewed, prioritized, and queued by the user before execution begins.

### A.7.1 Lobby Behavior

- All AI-initiated flows (from proactive chat suggestions, ambient analysis, etc.) and chat-initiated flows go to the lobby, never straight to execution
- User-initiated flows can be sent to the lobby or executed immediately, at the user's choice. The lobby is not just for AI proposals — humans use it to queue up work they want done but not right now.
- The lobby displays pending flows with their description, estimated scope (which boulders would be affected), and the triggering context (chat conversation, proactive suggestion, etc.)
- Users can reorder, approve, reject, or modify proposed flows in the lobby before they are queued for execution
- The lobby respects the one-active-flow-per-project constraint (A.8) — approving a flow from the lobby queues it behind any currently running flow
- A **cross-project lobby view** shows all pending flows across all projects the user has access to, so a tech lead can prioritize work across multiple projects from a single screen. The exact design of this view is TBD, but it must exist alongside the per-project lobby.

### A.7.2 AI as Read-Only Proposer

The AI chat interface and any ambient/proactive analysis operate in **read-only mode** with respect to the pipeline. They can:
- Read all documents, code, events, and pipeline state
- Propose new flows (which go to the lobby)
- Surface issues, stale documents, or opportunities for improvement

They cannot:
- Directly start flows, modify documents, or change pipeline state
- Bypass the lobby to execute changes

This ensures humans remain in control of what work actually happens, while the AI can freely analyze and suggest.

## A.8 Concurrency and Locking

The system uses **pessimistic locking** at the node level. Only one flow run or sub-run may be active per project at a time. This dramatically simplifies the concurrency story:

- No two flows can edit the same boulder simultaneously
- Sub-runs pause their parent, so there is no concurrent modification within a single project
- Lock acquisition follows the tree traversal order
- Locks are released on node completion, failure, or configurable timeout

## A.9 Resumability and Recoverability

- If a flow fails at any node, it can resume from the point of failure without re-running completed nodes
- Completed nodes are idempotent on re-run (re-running a completed node produces a new version but does not invalidate its dependents unless the output differs)
- All state changes are recorded as events, enabling replay and recovery
- Locks are automatically released on failure with configurable timeout

## A.10 Document Storage Model

Document content lives in two places with distinct roles:

- **PostgreSQL** is the operational store for document content. All reads during flow execution, context assembly, and UI rendering come from the database. pgvector embeddings are indexed against DB content directly.
- **Git/Gitea** receives committed snapshots at review boundaries — when a document reaches `awaiting_review` or `approved` status. Working drafts and AI review loops happen entirely in the database without git noise.

This means git history reflects meaningful checkpoints (reviewable and approved states), not every intermediate generation attempt. The event log tracks all state transitions regardless of whether a git commit was produced.

## A.11 Git Strategy

- **One commit per leaf node** — Each leaf boulder produces a single commit
- **Sub-run commits** contribute to the parent flow's branch hierarchy
- Every project is assumed to be a **monorepo** for v1. The data model supports multi-repo via the `{repository, folder}` mapping (Section A.1.2), but v1 flow orchestration, PR composition, and Gitea sidecar integration assume a single repository per project.
- The system is the sole code shipping mechanism for the project (aside from external changes propagated via A.2.5.2).

### A.11.1 PR Granularity

PR granularity is configurable per project to one of three levels: **system**, **component**, or **subcomponent**.

- **System level** (default) — One PR for the entire flow run. All leaf commits compose into a single PR against main.
- **Component level** — One PR per component. Each component's leaf commits compose into a PR against the run branch.
- **Subcomponent level** — One PR per subcomponent. Each subcomponent's leaf commits compose into a PR against the component branch.

### A.11.2 Branch Hierarchy

Flow runs use a **feature branch hierarchy** that mirrors the document DAG:

```
main
  └── run-branch (flow run)
       ├── component-a-branch
       │    ├── subcomponent-a1-branch (leaf commits here)
       │    └── subcomponent-a2-branch (leaf commits here)
       └── component-b-branch
            └── subcomponent-b1-branch (leaf commits here)
```

Approved documents are committed to the run branch (system level), since document review is complete before code generation begins. Code PRs are created at whichever level the project's PR granularity is configured to. Review flows upward through the branch hierarchy: subcomponent branches merge into component branches, component branches merge into the run branch, and the run branch merges into main. Catapult controls the review flow and communicates which branches are ready for review and in what order.

## A.12 Document Versioning

- All artifacts are versioned. Each generation or revision produces a new version.
- Event sourcing provides a complete audit trail of every state change.
- Users can revert to any previous version. Reversion appends new events (no destructive history changes).
- **Subtree revert** — Revert a node to version N, and the system automatically reverts each descendant to the version it was at immediately after the ancestor reached version N. This uses the event timeline to find the contemporaneous version of each child, so the user picks one point in the ancestor's history and the entire subtree snaps to its state at that moment. This avoids manually reverting descendants one by one and guessing which version corresponds to the ancestor's state.
- Each completed run produces a git commit checkpoint.

## A.13 Prompt System

- Each processing node type has a built-in prompt template with: system message, output format instructions, context assembly template, and revision instructions.
- Users can override any prompt field per stage per project.
- Model and temperature are configurable at three levels: project default, per-phase default, and per-node override. Defaults propagate downward.

## A.14 Credentials and Token Tracking

- The service is **BYO LLM credentials** — customers supply their own API keys through the application, not environment variables. Credentials are stored per-user.
- Token usage is tracked per node, per flow run, and per project. Users can see how many tokens each generation step consumed.
- Cost projection is deferred to a future version, but the tracking infrastructure is in place from day one.

## A.15 Real-Time Updates

- All connected clients receive live updates when artifacts are generated, statuses change, or flows progress.
- DAG visualizations, status indicators, and artifact viewers update in real-time.

### A.15.1 External Webhooks

Catapult emits its own webhook events for external integrations. Configurable per project, these webhooks notify external systems of significant pipeline events:
- Flow started, paused, completed, or failed
- Artifact ready for review (human review needed)
- Review SLA timeout exceeded
- PR created or merged
- Run completed with summary (boulders processed, artifacts generated, token usage)

Webhook payloads include enough context for external systems to take action (Slack notifications, CI dashboard updates, project management tool integration) without needing to query Catapult's API. Webhook endpoints are configurable per project by admins.

### A.15.2 External API

Catapult exposes a programmatic API for external tooling. The API provides read access to all project state (document DAG, pipeline status, event log, artifact content, review status, lobby contents) and write access to flow operations (propose flows to the lobby, leave deferred feedback, trigger actions permitted by the caller's role). Authentication uses the same per-user credentials as the web UI. The API enables: custom dashboards, Slack/Teams bots, project management tool integrations (Jira, Linear), CI/CD pipeline queries, and third-party tooling built on top of Catapult's data model.

## A.16 Auth and Multi-User Access

- Role-based access control: admin (full control), member (run flows, review, configure), viewer (read-only, can comment).
- Invite-based onboarding with time-limited tokens.
- **SSO/SAML support** for enterprise identity providers. Teams should be able to use their existing identity system rather than managing separate Catapult credentials.
- Per-user LLM credential storage.
- Per-user git credential storage for push/PR operations.
- **Session management**: configurable session timeout, concurrent session limits, admin-initiated forced logout.
- **Auth audit log**: all authentication and authorization events are logged separately from the pipeline event store — login, logout, failed login attempts, permission changes, role changes, invite creation and redemption, credential updates. This log is append-only, tamper-evident, and queryable by admins.

## A.16.1 Security and Compliance (SOC 2 Preparation)

The system is designed from the start to support SOC 2 Type II certification. These requirements apply to both self-hosted and managed deployments, though managed deployments bear the audit burden.

**Security (Trust Service Criteria CC6/CC7):**
- All network communication is TLS-encrypted: client ↔ Catapult, Catapult ↔ Gitea, Catapult ↔ PostgreSQL. No plaintext connections, even internal.
- Database encryption at rest — either Postgres TDE or volume-level encryption, configurable per deployment.
- All user-provided credentials (LLM API keys, git tokens) are encrypted at rest using per-tenant keys, never stored in plaintext.
- Input validation at all system boundaries: user-provided input, LLM output before it enters the pipeline, webhook payloads from Gitea, API request bodies. Reject malformed data at the boundary rather than propagating it.

**Availability (A1):**
- Health check endpoints for all services (Catapult, Gitea, PostgreSQL) — suitable for load balancer probes and uptime monitoring.
- Backup and disaster recovery: automated database backups with configurable retention, point-in-time recovery capability, documented recovery procedures. For managed deployments, RPO and RTO targets are defined per subscription tier.
- Graceful degradation: if Gitea is temporarily unavailable, the pipeline pauses git operations and resumes when connectivity is restored rather than failing runs.

**Processing Integrity (PI1):**
- Event sourcing provides a complete, immutable audit trail of all pipeline state changes.
- Git-before-DB commit ordering (A.24.10) prevents corrupted references.
- All LLM output is validated and parsed defensively (A.24.12) before entering the pipeline — malformed output is rejected, not propagated.
- Idempotent operations: re-running a completed node produces a new version only if the output differs (A.9).

**Confidentiality (C1):**
- Schema-per-tenant isolation (A.17.1) ensures no cross-tenant data access.
- Data classification: credentials and API keys are classified as sensitive and encrypted at rest. Document content and event data are classified as confidential and isolated per-tenant. User metadata (names, emails, roles) is classified as internal.
- Data retention and deletion: configurable retention periods per tenant. Tenant offboarding includes complete data export followed by full deletion (schema drop, Gitea org removal, vector embeddings purged). Deletion is auditable — a record of *what* was deleted and *when* is retained without retaining the data itself.
- For self-hosted deployments, BYO credentials means customer LLM traffic never transits Catapult's infrastructure — the customer's application calls the LLM provider directly.

**Privacy:**
- Minimal data collection: the system collects only what's necessary for operation (user identity for auth, credentials for integrations, document content for pipeline execution).
- For managed deployments: privacy policy, GDPR-compliant data handling for EU customers (data residency options, right to access, right to deletion, data processing agreements).
- LLM provider data handling is the customer's responsibility (BYO credentials), but the system should document what data is sent to LLM providers and provide configuration to control it.

## A.17 Multi-Tenancy

The system supports both self-hosted (single-tenant) and managed (multi-tenant) deployments from the same codebase.

### A.17.1 Tenant Isolation

Each tenant is isolated at the database level via **Postgres schemas** — one schema per tenant. Each tenant's event store, snapshots, documents, credentials, and project data live in a separate schema. This provides:
- Structural isolation without tenant_id columns on every table
- Per-tenant backup and restore
- Clean tenant export (schema dump) for customers migrating to self-hosted
- Independent event stores, so reconciliation (A.24.11) runs per-tenant
- Self-hosted deployments are simply single-tenant instances with one schema

### A.17.2 Gitea Tenant Isolation

Each tenant maps to a **Gitea organization**. Repositories live within the org, permissions scope to the org. For managed deployments, a shared Gitea instance with org-per-tenant is the default. Isolated Gitea instances are available as a premium option for enterprise tenants who require hard separation.

### A.17.3 Per-Tenant Resource Limits

Managed deployments enforce per-tenant limits to prevent noisy neighbors:
- LLM call concurrency limit per tenant (via per-tenant Oban queues)
- Git operation rate limiting
- Storage quotas (document content, git repos, vector embeddings)
- Limits are configurable per subscription tier

### A.17.4 Tenant Provisioning

Tenant lifecycle is automated: sign up → create Postgres schema → create Gitea org → configure webhooks → provision default boulder templates. Teardown follows a data retention policy with export-before-delete.

## A.18 Billing

Billing is an **optional, pluggable module** — disabled for self-hosted deployments, enabled for managed.

### A.18.1 Payment Processing

Payment integration is behind an adapter interface. The default implementation uses Stripe. The adapter handles:
- Subscription management (tiers, upgrades, downgrades)
- Usage-based billing components (token consumption, storage, projects)
- Webhook handling for payment events (subscription changes, payment failures)
- Free trial support

The billing adapter is AGPL-compatible (Stripe client libraries are MIT). Self-hosted deployments disable the billing module entirely — no payment code runs.

### A.18.2 Subscription Tiers

Tiers map to resource limits (A.17.3):
- **Free tier** — limited projects, limited LLM concurrency, limited storage. Enough to evaluate the system on a real project.
- **Team tier** — higher limits, multiple team members, review workflow features
- **Enterprise tier** — unlimited projects, isolated Gitea instance option, SSO/SAML, priority support, custom resource limits

Token costs are pass-through (BYO credentials), so subscription tiers govern platform usage, not LLM spend.

## A.19 Multi-Project Support

- Multiple independent projects, each with its own repository, document DAG, pipeline configuration, and event history.
- One active flow run per project at a time; different projects run concurrently.

## A.20 Bootstrap Flow

A one-time flow for self-bootstrapping. The only supported use case is onboarding a codebase that already has all required documents in the correct hierarchy and whose folder structure mirrors the boulder mapping assumptions.

- Takes as input: a codebase with documents already matching the scaffolding flow's output shape (requirements, architectures, plans) organized in the expected hierarchy
- Reconstructs the boulder hierarchy, dependency DAG, and document DAG from the existing documents and folder structure
- Synthesizes baseline events for the bootstrapped state — a `ProjectBootstrapped` event (or equivalent) that establishes the initial snapshot from the imported documents and folder structure. This ensures reconciliation (A.24.11) can rebuild the snapshot from events without special-casing bootstrap. Review records start fresh from the point of bootstrap.
- Destructive to existing project state; can only run once or on a fresh project
- After bootstrap, the project can use any standard flow to iterate

## A.21 AI Coding Assistant Integration

The coding portion of leaf boulder execution (plan creation and PR generation) is delegated to an AI coding assistant. The assistant has tools to read, navigate, and understand the current codebase directly — no separate code parsing or AST indexing is needed. The assistant works up implementation plans since it already has the tools to see the code in context. The document tree provides the "what needs to change" and the coding assistant handles the "how to change it" against the actual code.

## A.21.1 AI Sandboxing

All AI execution — coding assistants, document generation, template prompts — runs in a sandboxed environment. The sandbox enforces:

- **Filesystem scoping** — Coding assistants can only access files within the boulder's folder territory (A.1.2). A leaf boulder for `src/auth/` cannot read or write files in `src/payments/`.
- **No arbitrary network access** — AI execution can reach the configured LLM API endpoint and nothing else. No outbound HTTP to arbitrary URLs, no DNS resolution of external hosts.
- **No credential access** — The sandbox cannot access stored credentials (LLM API keys, git tokens, user secrets). Credentials are injected by the orchestrator into the specific API calls that need them, never exposed to the AI's tool environment.
- **Resource limits** — CPU, memory, and execution time are bounded per node execution. A runaway generation cannot consume unbounded resources.
- **Template isolation** — Boulder template prompts can only access the context categories they are configured for (A.3.5). A template cannot override system-level safety prompts or modify its own execution parameters. This is the primary defense against prompt injection via malicious template bundles (A.4.3).

Sandboxing is especially critical for managed multi-tenant deployments where untrusted LLM output executes on shared infrastructure.

## A.22 AI Chat Interface

A conversational AI interface scoped per project, allowing users to ask questions about the codebase and its documentation. The chat operates in **read-only mode** with respect to the pipeline — it can analyze everything but cannot directly modify documents, start flows, or change pipeline state. When the chat identifies issues or opportunities, it proposes flows that go to the flow lobby (A.7) for human prioritization.

### A.22.1 Capabilities

- **Document Q&A** — "Why does the authentication component use JWT instead of sessions?" The chat retrieves relevant architecture docs, plans, and review feedback via the pgvector semantic search layer (B.5) and answers with citations to specific documents and versions.
- **Codebase Q&A** — "How does the payment webhook handler work?" The chat uses the AI coding assistant's tools (A.21) to read and navigate the actual code, combining what it finds with the document DAG context.
- **Provenance queries** — "Who approved the database schema change and why?" The chat queries the event log and review history to trace decisions back through their full chain.
- **Cross-cutting questions** — "Which components would be affected if we changed the user model?" The chat uses the dependency DAG and architecture docs to identify impact across boulders.
- **Flow proposals** — "This component's docs are out of date with the code." The chat can propose flows (feature requests, refactors, upward propagations) that are sent to the flow lobby (A.7) for human review and prioritization. The chat never directly initiates execution.

### A.22.2 Review UI Integration

The chat is context-aware of the user's current review state. When a user is reviewing an artifact (document or code), the chat:
- Knows which artifact is currently being reviewed and can answer questions about it without the user having to describe it
- Can explain why a particular design decision was made, trace the provenance of a code change, or compare the current version against previous versions
- Can take review actions on behalf of the user — reject with feedback, approve, request specific changes — when explicitly asked. These are human review actions attributed to the user, not autonomous AI actions.
- Eliminates the need to copy-paste documents into a separate chat context to ask questions about them

### A.22.3 Proactive Chat

The chat can proactively surface issues without being asked:
- Documents that have drifted from the codebase (detected via periodic analysis)
- Review SLA timeouts approaching or exceeded
- Stale artifacts that haven't been regenerated after upstream changes
- Cross-cutting inconsistencies between sibling boulder architectures

Proactive notifications appear in the chat panel but do not interrupt the user's workflow. Any suggested actions go to the flow lobby (A.7), not direct execution.

### A.22.4 Context and Scoping

The chat is scoped to a single project. It has access to:
- All documents in the document DAG (current versions, with ability to reference historical versions)
- The codebase via the AI coding assistant's repository access
- The event log and review history
- The pipeline snapshot (current state of all nodes, runs, artifacts)
- The user's current review context (which artifact they're viewing, their position in the review queue)

Context assembly for chat queries uses the same pgvector retrieval and budget-based approach as pipeline execution (A.3.5), but with a query-driven retrieval strategy rather than a node-type-driven one.

### A.22.5 Conversation History

Chat conversations are persisted per project, per user. Users can reference prior conversations. Conversations are not part of the event-sourced pipeline — they are a read-only interface over the project's state, stored separately.

## A.23 Adoption and Trust

These requirements address the concerns of teams evaluating Catapult — particularly midsize engineering organizations that need to justify the investment and manage the risk of adopting a new workflow.

### A.23.1 Portability and No Lock-In

All project artifacts (documents, code, event history) are exportable at any time. Documents exist as markdown files in a git repository. Code is standard code in the same repository. If a team decides to stop using Catapult, they walk away with a fully functional codebase and a complete set of design documents — no proprietary formats, no data trapped in a database.

### A.23.2 Graduated Autonomy

The system supports a spectrum from fully supervised to fully autonomous. A team can start with every single node requiring human approval (treating Catapult as a "suggestion engine") and gradually increase auto-approval as trust builds. The spectrum is continuous — not a cliff between "manual" and "automatic." This is controlled via the auto-approval configuration (A.6.1) and review granularity settings (A.6.3).

### A.23.3 Human Override

At any point in a flow, a human can stop the run, correct course, and resume. The system should never be in a state where the only way forward is "trust the AI." Specific overrides:
- Pause any running flow immediately
- Reject and provide feedback on any artifact
- Prune entire subtrees that shouldn't exist (A.24.4)
- Force restart stuck nodes (A.24.4)
- Manually kick off sub-runs to fix upstream issues (A.5)

### A.23.4 Dry Run Mode

Structural estimation of a flow without making LLM calls or committing anything. Given a flow type and input, the system computes: the DAG shape (which boulders would be visited, in what order), the number of LLM calls required, the estimated token budget based on configured fan-out breadth and document size defaults, and which nodes would be created or regenerated. No LLM calls are made — the estimation uses configured defaults for fan-out breadth and document sizes. This lets teams evaluate scope and cost before committing budget, and is also useful for testing template and configuration changes.

### A.23.5 Diff-First Review

The review UI defaults to **diff view**, not full document view. No reviewer should be presented with a 20,000-word document and asked "is this good?" They see what changed since the last version. Full document view is available but is not the default. This applies to both document review and code review UIs.

The diff view supports multiple baselines:

- **Diff since last version** — The default. Shows what changed in the most recent generation/revision.
- **Diff since last view** — Accumulated changes since the current user last viewed this artifact. If a reviewer misses two review cycles, they see the total change across both, not just the latest. Per-user view tracking makes this possible.
- **Diff since event** — Changes since a specific event (a particular approval, a flow run completion, a point-in-time). The user selects the baseline from the event log or version history. This is essential for catching up after an absence or auditing what changed during a specific flow.

### A.23.6 Provenance Chain

Any document or piece of code is traceable back through its full generation chain: this code was generated from this plan, which was generated from this architecture doc, which was approved by Alice on March 3rd with these review comments. The provenance chain is surfaced in the UI — click any artifact to see its lineage. This is derived from the event log and document DAG edges.

### A.23.7 Rollback

Reversion to any previous project state is a single action. The event-sourced model (A.12) makes this possible — rollback appends new events, never destroys history. This is the single most reassuring capability for risk-averse teams and should be prominently surfaced in the UI.

### A.23.8 Self-Hosted Deployment

The entire stack (Catapult, Gitea, PostgreSQL) runs on the customer's infrastructure. No data leaves their network. Combined with BYO LLM credentials (A.14), customers control every external dependency. This is essential for teams with security or compliance requirements.

### A.23.9 Cost Visibility

Token tracking with model identifiers (A.14) is surfaced in the UI at the flow run level: "This scaffolding run used X tokens across Y calls, estimated cost $Z" (once cost projection is implemented). Even before cost projection, raw token + model data is visible per node and per run so teams can understand and predict their API spend.

## A.24 Operational Invariants (Learned from Siege Engine v1)

These requirements are derived from edge cases, bugs, and hard-won knowledge from Siege Engine's production use. They are non-negotiable for Catapult.

### A.24.1 Dependency Satisfaction

Dependencies are satisfied when a parent artifact has been **generated** (status in: `approved`, `awaiting_review`, `stale`), not only when approved. This allows downstream generation to proceed while upstream is still under human review. Without this, a single slow reviewer blocks the entire pipeline.

### A.24.2 Fan-Out Always Pauses for Review

Fan-out stages (which create or modify the boulder tree structure) must always pause for human review regardless of auto-approval settings. Structural changes — adding, removing, or reorganizing boulders — are too consequential to auto-approve. This is a hard override, not configurable.

### A.24.3 Blocking PR

If any outstanding PRs exist for a project from a prior flow run, new flows cannot start. All PRs from the prior run (at whatever granularity level the project is configured to) must be merged or closed before a new flow begins. This prevents the document DAG from drifting out of sync with the codebase. Merge order follows the branch hierarchy — subcomponent branches into component branches, component branches into the run branch, run branch into main. Sub-runs are exempt from this rule — they contribute to their parent flow's branch hierarchy and exist precisely to handle mid-flow corrections.

### A.24.4 Debugging and Administrative Tools

The system provides a set of administrative actions and debugging screens, separate from the normal review workflow.

**Administrative actions** (available to admins):
- **Prune** — Remove a node and its entire downstream cascade from the document DAG. For example, a fan-out produced a component that shouldn't exist. Unlike reject (which regenerates), prune deletes. Emits appropriate events for the removal.
- **Force restart** — Force a stuck or failed node back to pending and re-execute, bypassing normal status transition rules
- **Reset all** — Reset all nodes in the current run back to pending, clearing all generated state
- **Force sync / repair** — Rebuild the materialized snapshot from the event log. Detects and resolves orphaned executions, zombie runs, and stale state (see A.24.11)

**Debugging screens** (per project):
- **Snapshot viewer** — The current materialized snapshot in full, showing the authoritative state of all nodes, runs, and artifacts
- **Event log** — The last 100 events (filterable, pageable), showing what happened and in what order
- **Frontend log** — Client-side log capturing UI errors, WebSocket connection state, and user actions
- **Error panel** — Aggregated errors from both frontend and backend for the current project, with timestamps, stack traces, and source labels

### A.24.5 Cascading Readiness Re-Scan

After completing any node, the orchestrator must re-scan all pending nodes for newly unblocked work — not just the completed node's immediate children. Generating component A's architecture might unblock component B (which depends on A via the dependency DAG), and B may have already been passed in a linear scan. The scan must loop until no more work is found in a single pass.

### A.24.6 Centralized Run Completion

Run completion (transitioning a run to terminal status) must happen through exactly one codepath. Siege Engine had bugs where run completion logic was scattered across multiple callers, causing zombie runs that stayed in RUNNING status indefinitely. The single completion point should be in a `finally`-equivalent block of the main execution loop.

### A.24.7 Phase Boundary Checks Before Execution

Stop-point checks (phase boundaries, user-configured pause points) must be evaluated **before** entering a stage's execution, not after. The check acts as a gate: stages past the stop point are never entered. Checking after execution means boundary-crossing stages run before the pause is detected.

### A.24.8 Cross-Run Execution Deduplication

Before creating a new execution for a node, check for existing RUNNING executions for the same node **across all runs**, not just the current run. Scoping this check to a single run allows duplicate executions when sub-runs or manual triggers overlap.

### A.24.9 Retries Are Sub-Runs

Failed executions are not retried in-place. A retry is a sub-run: it pauses the current run, creates a new run scoped to the failed node, executes, and returns control to the parent. This keeps the execution model uniform — there is no special "retry" concept, just the same sub-run machinery used everywhere else. The original failed execution remains in its terminal state in the event log.

### A.24.10 Git-Before-DB Commit Ordering

When an operation produces both a git commit and a database event, the git commit must happen **before** the database commit. If the database succeeds but git fails, the event log references a nonexistent commit — corrupted event history that is difficult to recover from. If git succeeds but the database fails, the result is an orphaned git commit that can be cleaned up trivially without data loss. Always order: git commit → DB commit.

### A.24.11 Reconciliation on Startup

On server startup, the system must reconcile all projects: rebuild materialized state from events, detect and resolve orphaned executions (RUNNING with no active job → mark FAILED), complete zombie runs (RUNNING with no active executions → mark FAILED), and cancel stale queued jobs. This is a first-class recovery mechanism, not an afterthought.

### A.24.12 LLM Output Parsing Resilience

LLM output format is unreliable. All structured output extraction (component lists, dependency DAGs, code files, plans) must use multiple parsing strategies with fallbacks. Try strict parsing first, fall back to regex extraction, then to smaller-model re-extraction. Never fail a stage because the LLM returned valid content in an unexpected format.

### A.24.13 LLM Concurrency Limits

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
- Token tracking per call with model identifier recorded alongside token counts, aggregated per node, flow run, and project. Model must be stored with tokens to enable future cost calculation.
- Model and temperature configurable at project, phase, and node levels
- Multiple LLM providers supported behind a common interface

## B.10 Licensing Model

Catapult uses a **dual-license model**:

- **AGPL v3** for the public open-source release. Anyone can use, modify, and deploy Catapult freely. Modifications to the core must be published if the modified version is offered as a network service. This closes the SaaS loophole that plain GPL leaves open — cloud providers cannot run a modified Catapult as a managed service without contributing back.
- **Commercial license** available for organizations whose legal or compliance requirements are incompatible with AGPL. The commercial license permits proprietary modifications, private deployment without source disclosure, and use of proprietary optional dependencies.

**Architectural implications for dual licensing:**
- The core system (pipeline engine, event sourcing, document DAG, review workflow, LiveView UI) is AGPL and must not depend on any proprietary libraries.
- **Oban**: The core depends only on Oban core (Apache 2.0, AGPL-compatible). Oban Pro features (unique jobs, batch processing, web dashboard) are behind an optional module that is not required for core functionality. Commercial licensees may use Oban Pro at their discretion.
- **Gitea sidecar**: Communicates over HTTP — a separate process, not a derivative work. No licensing conflict.
- **Plugin/extension boundary**: Third-party tools communicating with Catapult over HTTP/API are not derivative works. Plugins loaded into the Elixir runtime are derivative works under AGPL. This boundary must be documented clearly.
- **Contributor License Agreement (CLA)**: Required for contributions to the core repository, granting the project the right to distribute contributions under both AGPL and commercial licenses.
