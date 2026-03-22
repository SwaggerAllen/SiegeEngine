# Catapult — Requirements

## Core Concept

Catapult is an AI-powered document generation and code scaffolding system. It takes a project description and produces a full tree of design documents (requirements, architectures, plans) and code through a structured, reviewable pipeline. The system maintains two interconnected graph structures: a **pipeline DAG** that defines *what work to do* and a **document DAG** that represents *what's been produced*.

Each node in the document DAG that has its own sub-DAG of processing steps is called a **boulder**. Boulders exist at three levels: system (one per project), component (produced by system-level fan-out), and subcomponent (produced by component-level fan-out). Leaf artifacts like plans, code files, and reviews are outputs *of* a boulder's sub-DAG, not boulders themselves.

---

## 1. Dual DAG Architecture

- **Pipeline DAG**: A directed acyclic graph of processing stages. It defines the shape of the work — which AI generation steps run, in what order, and with what inputs. The pipeline DAG is a sequence of 5 phases, each containing a configurable sub-DAG template. When a phase fans out (e.g., system → components), the sub-DAG template is instantiated once per boulder, producing the full pipeline graph.
- **Document DAG**: A directed acyclic graph of artifacts (documents and code files) produced by the pipeline. Each node is a versioned document with status tracking. The document DAG mirrors the project's hierarchical decomposition: a single system boulder at the root, component boulders beneath it, subcomponent boulders beneath those, and leaf outputs (plans, code, reviews) at the bottom. Edges represent both parent-child relationships and cross-cutting dependency relationships between sibling boulders.
- The pipeline DAG drives generation; the document DAG records results. A user viewing the pipeline DAG sees "what stages will run and their status." A user viewing the document DAG sees "what documents exist and their approval state."

## 2. Five-Phase Pipeline Structure

Each flow (scaffolding, bug fix, feature request, refactor) walks the document DAG in five phases. Each phase has a sub-DAG template that defines the default processing steps for that phase. The sub-DAG template is instantiated once per boulder at that level of the document hierarchy.

- **Phase 1 — Input Expansion**: Takes raw user input (project description, bug report, feature request) and expands it into a structured requirements document. Default sub-DAG: one requirements generation node. Produces a single system-level requirements document for the system boulder.
- **Phase 2 — System Architecture**: Takes the expanded requirements and produces a system-level architecture for the system boulder. Default sub-DAG: one architecture generation node feeding into one conditional fan-out node. The fan-out node decomposes the system into component boulders and establishes a dependency DAG among them.
- **Phase 3 — Component Architecture**: Instantiated once per component boulder produced by Phase 2's fan-out. Takes the parent system architecture plus the boulder's slice of requirements and produces a component-level architecture. Default sub-DAG: one architecture generation node and one conditional fan-out node (which decomposes into subcomponent boulders if warranted).
- **Phase 4 — Subcomponent Architecture**: Instantiated once per subcomponent boulder produced by Phase 3's fan-out. Produces a subcomponent-level architecture document. Default sub-DAG: one architecture generation node. No further fan-out.
- **Phase 5 — Leaf Processing**: Instantiated once per leaf boulder (components without subcomponents, or subcomponents). Produces implementation artifacts. Default sub-DAG: one implementation plan node, one code generation node, one code review node (sequential).

## 3. Flow Types

The system supports multiple flow types, each defining its own sub-DAG templates per phase. Only one flow may be active per project at a time.

- **Scaffolding Flow**: The default flow. Generates all documents from scratch, walking the full document DAG top-down through every boulder. Uses the default sub-DAG templates described in Section 2. Produces a complete set of documents and code for a new project.
- **Bug Fix Flow**: Input is a pull request with title and description (not a free-text prompt). Each phase's sub-DAG template is tailored for diagnosis: at each boulder level, the AI produces a plan document analyzing which child boulders need changes, then only visits those children. Generates fix plans and code patches rather than full documents.
- **Feature Request Flow**: Input is a feature description. Similar tree-walking strategy to bug fix — produces an impact analysis plan at each boulder level determining which existing boulders need modification and whether new boulders are needed. Generates updated documents and code for affected boulders only.
- **Refactor Flow**: Input is a refactoring objective. Walks the tree producing refactoring plans at each boulder level, identifying structural changes needed. Can modify the boulder decomposition itself (splitting, merging, reorganizing boulders).

## 4. Fan-Out and Dependency DAGs

- Fan-out nodes are conditional — the AI decides whether decomposition is needed based on complexity. A simple system might not fan out at all; a complex one might produce dozens of component boulders.
- When a fan-out node fires, it produces: (a) a list of child boulders with names and descriptions, and (b) a dependency DAG among those boulders specifying which depend on which.
- The dependency DAG governs execution order during generation. Independent sibling boulders (no dependency edges between them) can be processed in parallel. A boulder with dependencies waits for all its dependency boulders to complete first.
- Cross-boulder dependency edges are visible in the document DAG, allowing users to understand the relationships between components.

## 5. Configurable Sub-DAGs

- Users can modify the sub-DAG template for any phase before or during a flow. For example, adding an extra review node, removing the code review step, or inserting a custom analysis stage within a boulder's processing pipeline.
- Each node in a sub-DAG template specifies: its processing type (generation, review, fan-out), its prompt template, its input sources, and its output artifact type.
- Sub-DAG modifications persist per project and are version-tracked.

## 6. Stopping Points and Run Control

- Flows execute with configurable stopping points: end of phase, after every artifact, or before code generation. When a stopping point is hit, the flow pauses and waits for user action.
- Users can start a flow from any boulder or node in the pipeline (not just the beginning), resume a paused flow, or trigger regeneration downstream from a specific artifact.
- Run-scoped generation allows targeting a specific boulder (e.g., "regenerate only the authentication component boulder's architecture").
- Regen-downstream marks all artifacts downstream of a given node as stale and regenerates only those that were previously AI-generated (skipping nodes that were never generated in the first place).

## 7. Review and Approval Workflow

- Each generated artifact goes through an AI self-review loop before becoming available for human review. The AI review produces structured feedback: a quality score, a recommendation (approve/revise/reject), and detailed notes. If the AI recommends revision, it automatically regenerates the artifact incorporating its own feedback, up to a configurable number of loops.
- After AI review, artifacts enter "awaiting review" status for human review. Humans approve or reject artifacts with text feedback only — there are no inline human edits. All change requests are expressed as written feedback that the AI incorporates in a subsequent revision pass. This constraint keeps concurrency simple (no merge conflicts between simultaneous human edits and AI regeneration).
- Rejecting an artifact propagates staleness downstream — all artifacts that depend on the rejected one are marked stale, signaling they need regeneration once the upstream issue is resolved.
- Status chain: pending → generating → ai_reviewing → awaiting_review → approved / rejected / stale.

## 8. Context and Input Resolution

- Each processing node receives its inputs from two sources: (a) its parent boulder's artifacts from the prior phase of the document DAG, and (b) its direct dependency boulders' artifacts within the same phase (as defined by the dependency DAG from fan-out).
- There is no manual per-document stage injection. Input routing is determined structurally by the DAG topology. If a component boulder depends on another component boulder, the dependent automatically receives the dependency's artifacts as context.
- External reference documents (uploaded by the user) are attached at the appropriate level of the document DAG and flow downward as context to all descendant boulders.

## 9. Event Sourcing and Time Travel

- All state changes are recorded as an append-only event log. Events include: artifact created, artifact status changed, flow started, flow paused, artifact content updated, fan-out completed, etc.
- The system maintains materialized snapshots derived from the event log for fast reads (current pipeline state, current artifact statuses).
- Users can revert to any previous checkpoint. Reverting does not delete history — it appends new events that record the reversion and creates new artifact versions containing the restored content. The old content is preserved as a prior version in git, maintaining a complete audit trail.
- Each completed run produces a git commit checkpoint, enabling reconstruction of project state at any point in history.

## 10. Git Integration

- Each project is backed by its own git repository. Artifacts are written to files and auto-committed as they are generated, with the commit SHA recorded on the artifact for traceability.
- PR creation is supported from the UI. A "blocking PR" concept prevents new flows from starting until an outstanding PR is merged or closed, ensuring the codebase stays in sync with the document DAG.
- Git history is used for time travel: reverting to a prior state reads file content from the appropriate git commit and writes it as a new commit with a new artifact version. This preserves forward history (no destructive git operations) and ensures every state change — including reversions — is a versioned, auditable event.
- Remote repository support with per-user GitHub credential storage for push/PR operations.

## 11. Auth and Multi-User Access

- Role-based access control with three levels: admin (full control, manages invites and credentials), member (can run flows, review artifacts, configure prompts), and viewer (read-only access to documents and DAGs, can add comments).
- Invite-based onboarding: the first user is auto-promoted to admin. Subsequent users register via time-limited invite tokens created by admins. Invites specify the role granted.
- Per-user GitHub credential storage so each team member can push/create PRs under their own identity.

## 12. Prompt System

- Each processing node type has a built-in prompt template with: system message, output format instructions, context assembly template, and revision instructions (used during AI self-review loops).
- Users can override any prompt field per stage per project. Overrides are stored in a prompt configuration record linked to the stage definition.
- Model and temperature are configurable at three levels: global project default, per-phase default, and per-stage override. Defaults propagate downward (stage override beats phase default beats project default).
- A prompt template registry maps template keys to built-in prompt implementations, making it easy to add new processing node types.

## 13. Code Artifact Handling

- Code generation nodes produce markdown-wrapped code blocks with embedded file path annotations (e.g., `# filepath: src/auth/login.ts`). The system extracts file paths, language identifiers, and content from these blocks.
- Extracted code files are written to the project's git repo at the specified paths. Language detection from fenced block markers enables syntax-appropriate handling.
- Code review nodes receive the generated code plus the boulder's architecture and plan documents and produce structured review feedback, which feeds back into the code generation node for revision (following the same AI self-review loop pattern).

## 14. Real-Time Updates

- WebSocket connections provide live updates scoped per project. All connected clients receive broadcasts when artifacts are generated, statuses change, or flows progress through boulders.
- Connections are authenticated and automatically reconnect on disconnection.
- The frontend DAG visualizations, status indicators, and artifact viewers all update in real-time without polling.

## 15. UI and Visualization

- Interactive DAG visualization for both the pipeline DAG and document DAG, with automatic layout, color-coded status indicators per boulder and leaf node, minimap navigation, and click-to-select behavior.
- Artifact viewer with markdown rendering, version diff view (unified diff against previous version), AI review feedback display, and a comments panel.
- Threaded comments on artifacts — comments persist across regenerations and are tied to the artifact version they were written against. Viewers can comment; only members and admins can trigger flows or submit review feedback.
- Run selector allowing users to switch between the live state and any historical run's snapshot, enabling review of how the project evolved over time.
- Flow-scoped controls on boulder and leaf nodes: start, resume, and regenerate actions available contextually based on node state.

## 16. Multi-Project Support

- The system supports multiple independent projects simultaneously, each with its own git repo, document DAG, pipeline configuration, boulder hierarchy, and event history.
- Only one flow may be active per project at a time, but different projects can run flows concurrently.

## 17. Bootstrap Flow

- A one-time-use self-bootstrapping flow for onboarding existing codebases. Takes as input: (a) a collection of documents matching the shape of the default scaffolding flow's output (requirements, architectures, plans), and (b) an existing codebase.
- The bootstrap flow parses the provided architectures top-down to reconstruct the boulder hierarchy (system → components → subcomponents) and the dependency DAG between sibling boulders, then aligns the codebase files to the appropriate leaf nodes.
- Once bootstrapped, the project can use any standard flow (bug fix, feature, refactor) to iterate on the existing codebase, with the AI having full context of the documented architecture across all boulders.
- This flow is destructive to any existing project state and can only be run once (or on a fresh project).
