# SiegeEngine v2 Architecture

Living design doc for the v2 rewrite. Captures the structured-model rearchitecture discussion. This is the target architecture, not the current state of the code — the current code will be gutted before v2 is built.

---

## Problem statement

In v1, most changes have to propagate from the system level down. This makes system-level docs grow without bound and undermines the benefit of breaking work into smaller chunks. The underlying cause is that documents are the source of truth and the DAG is a linear-ish chain of ever-more-specific docs derived from a single god doc. There's no good way to make a localized change without touching everything upstream of it.

v2 inverts this: a **structured model** is the source of truth, documents are **derived views** of the model, and changes propagate as **diffs** through a unified DAG in both directions.

---

## Data model

### Feature decomposition

The input doc is decomposed into a machine-readable breakdown of **features**, not a prose system doc. A feature is the unit a user thinks in ("billing", "collaborative editing"). Features are slices, not containers — a feature can span multiple systems.

### Feature → Responsibility → Component

- Features decompose into **responsibilities** (many-to-many with features).
- Each responsibility maps to exactly one **component** (many responsibilities per component, but one component per responsibility).
- This asymmetry is load-bearing: it's what makes per-component review tractable, because all the diffs touching a component can be grouped naturally.

### Component structure (recursive)

```
Component {
  responsibilities: [Responsibility]
  api:              [Endpoint / Interface]
  dependencies:     [ComponentRef]
  subcomponents:    [Component]   // same shape all the way down
}
```

- Subcomponents have subresponsibilities, their own API, their own deps.
- Implementation docs live at the component/subcomponent level (what v1 called "architectures").
- Conditional fanout is preserved — a component decides how it decomposes.

### Unified DAG

- No more dual domain/frontend DAGs.
- One graph with two node **kinds**: domain nodes and presentational nodes.
- Presentational nodes are strictly in layers after domain nodes.
- Presentational nodes that are "primary views" into domain state carry a `domain_parent` edge (cross-cutting reference, not a dependency).
- Admin functionality is just another feature, not a new node type — it decomposes into the same component shapes (possibly backed by event-stream introspection rather than traditional CRUD).

### Source of truth inversion

- The structured model is the source of truth.
- Documents are derived views of the model.
- Users do not edit documents directly. All writes to the model go through the LLM.
- This is the single biggest philosophical shift from v1.

---

## Propagation model

### Everything after initial generation is diffs

- Event-sourced history means we can always compute the delta between a node's current state and its state at the last successful generation of any neighbor.
- Regen prompts receive **deltas**, not full docs from adjacent nodes.
- **Delta attenuation** (post-MVP): when the LLM sees a delta that doesn't affect it, it emits an empty delta and the cascade stops on that branch.

### Bi-directional regeneration

- **Downward:** follow dependency edges, regenerate children with parent deltas.
- **Upward (two-pass, post-MVP):** walk up through parents to the system level, then flip and walk back down through all children of touched parents. Generation at fanout boundaries decides which children to regenerate — not a blanket "regen everything downstream."

### Auto-propagation with batched review (post-MVP)

- Propagation runs automatically after an edit.
- The user doesn't review each hop in isolation. Changes are batched and presented as a combined navigable diff across every affected node.
- Version/view navigation via dropdown on each node so you can see "what this node looked like when its parent was last reviewed."

### Change summaries

- Generated as part of the generation step — the LLM appends a change summary section to its output.
- Stripped before storage but captured into a structured change log.
- Becomes queryable audit history for free, and feeds the vector-search index.

---

## Review model

### Per-component scoping

Because each responsibility has exactly one component, we can group all diffs touching a component and review them together. **Review pass = component**, not feature, not node.

### Vector search as safety net (post-MVP)

- Embed: implementation docs, responsibility descriptions, API definitions, change summaries.
- Query at **review-assembly time**, not generation time.
- For each component under review, pull semantically similar chunks based on deltas + touched responsibilities + API surface.
- Purpose: catch cross-cutting implications the graph doesn't capture. Not primary context feeding.

---

## Editing and UI model

### Read-only generated views + prose feedback + structured UIs

- All generated documents render **read-only**.
- Every node accepts **prose feedback** as input to regen.
- A small set of specific UIs handle structural operations that are miserable to do through prose.

### Structured UIs

1. **Feature → responsibility mapping** — drag-drop page, assign only
2. **Responsibility → component mapping** — drag-drop page, assign only
3. **Component / subcomponent decomposition** — graph editor (Cytoscape), create/move/delete
4. **Subresponsibility → subcomponent mapping** — drag-drop page, assign only
5. **Dependency editor** — graph editor, create/delete edges with cycle prevention
6. **Domain-parent editor** — same graph editor, different edge type

All six UIs can create new entities and support **promotion/demotion** between tiers. Every other kind of edit happens through prose feedback.

### Drag-drop pages are separate, not unified

- Pages are separate per step (not a single unified nested view).
- Rationale: by the time the user is doing a downstream mapping, the upstream ones should be relatively stable, and separate pages fit mobile form factors where more than two columns is impractical.
- Mobile interaction is tap-to-select + tap-to-place, not long-press drag.

### Graph editors (component decomposition, dependencies)

- Desktop: click-drag to create edges, click to select.
- Mobile: tap-two-nodes-to-connect.
- Dependency editor prevents cycles upfront (DFS from target to source before accepting an edge).
- Dependencies and domain-parent edges are different edge types with different modes/colors in the editor.

### UI-as-prose-generator

UI actions do not mutate the model. They produce **prose instructions** that are fed into the regen pipeline. The LLM is always the one writing to the model.

Why this is better than direct mutation:
- Model stays in LLM-reachable states (no inconsistencies from UI bypasses).
- Loose coupling: UI only describes changes, doesn't apply them. Schema changes don't break the UI.
- Unifies code paths: "dragged responsibility X to component Y" and "typed 'move responsibility X to component Y'" become the same downstream pipeline.
- Prose translation is an audit log entry for free.

### Pending-change queue

- UI operations queue up prose instructions without touching the model.
- User hits "apply changes" to run regen over the queue.
- Discard the queue for a free undo of not-yet-applied changes.
- The batched review flow **is** the preview — no separate preview infrastructure needed.

---

## Instruction vocabulary

UI actions and prose feedback both produce bulleted instructions consumed by regen. Every instruction references entities by **stable ID** with human-readable names for intent:

- **Create** — new entity with content
- **Delete** — remove entity (cascades handled by regen)
- **Rename** — change display name, preserve content and lineage
- **Reassign mapping** — move X to be under Y
- **Promote / demote** — change tier, preserve content and lineage
  - subcomponent ↔ component
  - subresponsibility ↔ responsibility
  - responsibility ↔ feature (rare)
- **Merge** — combine multiple entities, reconcile overlapping content
- **Split** — one source into multiple destinations, distribute content
- **Add / remove dependency edge**
- **Add / remove domain-parent edge**

### Lineage preservation

Every structural operation that changes identity (rename, promote, reparent, merge, split) must carry lineage references. Without them, regen starts fresh and throws away prose the user has been iterating on.

Example prose instructions (bulleted, with stable IDs):

> - Rename component `comp_auth_svc_abc123` to "IdentityService" (preserve existing content)
> - Promote subcomponent `subcomp_token_store_def456` under `comp_auth_svc_abc123` to a top-level component (preserve existing content and responsibilities)
> - Merge components `comp_auth_svc_abc123` and `comp_id_svc_xyz789` into a single component named "IdentityService" (reconcile overlapping content, prefer `comp_auth_svc_abc123` for conflicts)

The LLM sees both: the name for intent, the ID for lineage. Regen prompts then say "here is the previous implementation doc for `comp_auth_svc_abc123`, produce the new version for `IdentityService` incorporating these changes," and content carries forward naturally.

### LLM has leeway

Instructions are **directives, not mutations**. "The user wants X in Y, figure out how to make that coherent" rather than "set X.component = Y". If a user moves something somewhere it doesn't fit, the LLM has latitude to restructure the destination, push back, or split the incoming thing.

---

## Cross-cutting concerns

Because responsibilities map many-to-one to components, "cross-cutting" never means "this responsibility lives in multiple components." It means one of:

1. **Promote to a higher tier** — a subresponsibility needed by two subcomponents becomes a responsibility of their shared parent component.
2. **Extract as a new component** — a concern needed by three components becomes a standalone component that the three depend on. (This is the most common real answer.)
3. **Split into multiple responsibilities** — worst option, duplicates content.

Option 2 is a promotion followed by dependency edits. Natural flow: user notices cross-cutting, promotes the subresponsibility to a standalone component, opens the dependency editor to wire up the dependents. Two UI operations, both already in the set.

---

## MVP scope

**Included in MVP:**
- Structured model (features, responsibilities, components, subcomponents) as source of truth
- Unified DAG with domain + presentational nodes and domain-parent edges
- Diff-based regen prompts (even without optimizing which nodes run)
- Change summaries as part of generation
- Per-component review scoping
- Read-only generated views
- All six structured UIs with create + promotion/demotion
- Prose feedback on all nodes
- Full instruction vocabulary with stable-ID lineage references
- Pending-change queue with batched review

**Deferred post-MVP:**
- Delta attenuation (nice optimization, not load-bearing)
- Vector search review augmentation (nice safety net, not load-bearing)
- Two-pass upward propagation automation (manual "regen children from here" button works for MVP)
- Auto-propagation (explicit regen buttons for MVP; auto comes once regen quality is trusted)

The MVP is still a lot, but it's the irreducible core. The deferred items are optimizations on a working system.

---

## Rewrite plan (high-level)

This is a **rewrite of the pipeline and document/DAG core**, done in-place in this repo on top of gutted v1.

### Survives v1 → v2

- Auth, project management, user/workspace plumbing
- HTTP layer scaffolding, WebSocket infrastructure
- Frontend shell: React Query patterns, layout components, build setup
- LLM client, model config, prompt templating infrastructure
- Cytoscape wrapper (content changes, primitives don't)
- Event-sourced execution engine's *shape* (reducer + event log) — events themselves change

### Gutted

- `artifact_type` enum and everything keyed off it
- Dual-DAG logic (backend service split and frontend `dag_type` param)
- `component_map` / `sub_component_map` / `frontend_*_map` fanout artifacts
- Staleness propagation system (replaced by diff-based propagation)
- Stage registry and all current stage templates
- `ComponentDefinition` and related v1 models
- Current review flow (`stage_awaiting_review`, per-artifact review UI)
- Current editor's write path (views become read-only)

### Two-step plan

1. **Gut phase** — delete v1 core, keep scaffolding, audit surviving code for v1 assumptions.
2. **Build phase** — implement v2 data model, pipeline, DAG, UIs on top of the gutted base.

Detailed plans for each step to be written separately.

### Catapult as the first v2 project

Catapult is SiegeEngine's only real user and it needs all the bootstrapping changes discussed here. It gets rebuilt from scratch on v2 as v2's first project, and becomes the benchmark for whether the new model works. No migration path — existing v1 Catapult state is thrown away.

---

## Open questions / things to revisit

- Exact schema for the structured model (component / responsibility / feature shapes)
- How stable IDs are minted and surfaced (slug-based? opaque IDs with name aliases?)
- Where change summaries live in the event stream vs. a separate log
- How the feature decomposition prompt is structured (though feature-extraction risk is considered low given v1's fanout reliability)
- Mobile-specific interaction details for the graph editors
