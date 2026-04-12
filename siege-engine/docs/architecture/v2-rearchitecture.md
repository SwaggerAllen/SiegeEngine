# SiegeEngine v2 Architecture

Living design doc for the v2 rewrite. Captures the structured-model rearchitecture discussion. This is the target architecture, not the current state of the code — the current code will be gutted before v2 is built.

---

## Problem statement

In v1, most changes have to propagate from the system level down. This makes system-level docs grow without bound and undermines the benefit of breaking work into smaller chunks. The underlying cause is that documents are the source of truth and the DAG is a linear-ish chain of ever-more-specific docs derived from a single god doc. There's no good way to make a localized change without touching everything upstream of it.

v2 inverts this: a **structured model** is the source of truth, documents are **derived views** of the model, and changes propagate as **diffs** through a unified DAG in both directions.

---

## Core principle: approval gates propagation

A change to a node does not affect its neighbors until the change is approved. Every edit — prose feedback, a structured UI action, or a propagated diff from an adjacent node — lands as a pending state on the edited node. Downstream regen doesn't run until the user accepts that node's new version.

This is what makes iteration tractable. Without the gate a single edit at the top ripples instantly and the user is chasing cascades they didn't ask for. With the gate you can sit on a draft, iterate on it in isolation, and release it downstream only when it's right. The pending-change queue and batched review flow are the user-facing expression of this principle.

Corollary: the feature expansion is itself a node (see *Generation order and the system architecture layer*). You iterate on it as a prose doc, approve it, and only then do feature nodes get minted or updated downstream. The same gate applies at every tier — no node's changes take effect on other DAG nodes until that node itself is approved.

---

## Data model

### Generation order and the system architecture layer

The cold start — building a project from an input doc — runs through a fixed topological order. Each layer is a node (or set of nodes) with its own prose, its own approvals, its own regen prompt:

1. **Input doc** — the raw prose the user brings in. The only node the user authors directly.
2. **Feature expansion** — a prose decomposition of the input into features, iterated on as a standalone document node *before* any feature nodes exist. Approving the expansion is what mints (or updates) the individual feature nodes downstream.
3. **Features ↔ responsibilities** — each feature decomposes into responsibilities; the mapping is its own editable artifact.
4. **System architecture** — a top-level doc that lays out every component, its API intent (what it exposes at a contract level), and its dependency edges. This is the cold-start resolver: it's where the structure of the DAG comes from before any component has been written.
5. **Component architecture docs** — generated in dependency topological order. Each consumes the system architecture's entry for it (including its intended API) plus the public surfaces of its dependencies.
6. **Subcomponent architecture docs** — generated in dependency topological order within each component.
7. **Implementation docs** — the leaf prose under each component/subcomponent.
8. **Code** — generated as a final leaf pass, implementation by implementation, in dependency topological order.

The system architecture resolves the chicken-and-egg of "component A's regen needs component B's public surface, but B hasn't been generated yet" by committing to API intent up front. Component archs then flesh the intent into full public-surface detail, and the system architecture's API entry for each component is a transcluded fragment of the component arch (see *Shared fragments*) — so drift between "what we said" and "what got built" is detectable as a fragment diff.

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

### Architecture documents are parseable

Implementation/architecture docs (the doc each component or subcomponent owns) are not free-form prose. They have a stable section structure the model can parse, because sibling components' regen prompts pull each others' API surfaces out of these docs and stuffing the entire dependency doc into every dependent's prompt would blow up context.

Required sections, each wrapped in an XML tag:

- `<public-surface>` — the component's API. Types, function signatures, methods, events — anything a dependent is allowed to reach for. This is what gets extracted and handed to dependents at regen time.
- `<private-surface>` — internal types and helpers. Visible to the component's own subcomponents during their regen, but not to sibling dependents.
- `<dependencies>` — the list of sibling components this one reaches for, by stable ID. Parseable separately because it feeds dependency-edge edits and cycle detection.
- `<implementation>` — the prose body. Behavior, invariants, sequencing, edge cases. Not structurally parsed; consumed whole when the component itself or its children regen.

Inside `<public-surface>` and `<private-surface>`, code-shaped content lives in language-agnostic fenced code blocks. The parser doesn't inspect the code — it just pulls the tagged section whole. This matters because Catapult (v2's first real project) is written in Elixir, and the parser must not care what's inside the fences.

**Tags are displayed, not stripped.** User-facing rendering of architecture docs keeps the XML tags visible. SiegeEngine's audience is technical; a "stored vs shown" transform would only add bugs without adding clarity.

The public/private split is real architectural work the LLM does at authoring time, not a post-hoc tagging pass. A wrong export decision propagates as silent context loss to every dependent, so the public-surface section is itself a reviewable artifact — surfaced as a derived view on the component, and probably promoted to one of the structured UIs if the export decisions turn out to be a frequent source of feedback.

### Shared fragments (transclusion)

Some content belongs to more than one node. The most important case: a component's public surface is both part of that component's architecture doc *and* part of the system architecture's entry for it. Duplicating the content guarantees drift. Instead, each parseable section is a **fragment** with its own stable ID, and both docs transclude it.

Fragment ID format: `<owner_id>_<fragment_kind>`. The fragment kind vocabulary is fixed:

- `pubapi` — the `<public-surface>` section
- `privapi` — the `<private-surface>` section
- `deps` — the `<dependencies>` section

Example: `comp_a3f7k2m9_pubapi` is the public surface fragment owned by component `comp_a3f7k2m9`. The parser splits on the last underscore; `<owner_id>` is stable and opaque (see *ID scheme*), `<fragment_kind>` is validated against the vocabulary.

Properties:

- **Fragments don't move.** They're tied to their owner. Merge/split of an owning component cascades to its fragments automatically.
- **Diffs operate on fragments, not whole docs.** When a component's public surface changes, the fragment's diff is what propagates. Dependents key on the fragment ID, so a change confined to `<implementation>` doesn't invalidate dependents that only read the `pubapi` fragment.
- **Disagreement detection is a fragment diff.** If the system architecture claimed a component would expose one API and the component arch ended up exposing a different one, the system architecture's copy of `comp_X_pubapi` and the component arch's copy diverge. That's the drift signal, surfaced naturally.

### ID scheme

Every entity in the model gets a stable ID of the form `<kind>_<8 base32 Crockford chars>`, e.g. `comp_c5h9m4p1`, `feat_bqr3t8wv`, `resp_k2p7xn4m`.

Kind vocabulary:

- `feat` — feature
- `resp` — responsibility
- `comp` — component (tier-agnostic: top-level components and subcomponents both use `comp_`, because promotion/demotion between tiers must not change the ID)
- `impl` — implementation doc (leaf under a component)
- `edge` — dependency or domain-parent edge, when edges need their own identity

Fragment IDs extend this as described above.

Design notes:

- The 8-character suffix is fully opaque. It is not derived from the name, because rename must not change identity and a slug-based ID would force either renaming the ID (breaks lineage) or letting the ID lie about the current name.
- Names are always carried alongside IDs in prose instructions, regen prompts, and UI. The ID is for lineage, the name is for intent; the LLM sees both (see *Instruction vocabulary*).
- Lineage across rename / promote / reparent / merge / split is tracked in the event log, not encoded in the ID. An ID is stable for the lifetime of an entity and gone when the entity is deleted; it is never reused.

### Unified DAG

- No more dual domain/frontend DAGs.
- Domain and presentational nodes share the same **shape**: Feature → Responsibility → Component → Subcomponent. The distinction is a `kind` tag on the node, not a different data model.
- Presentational nodes are strictly in layers after domain nodes.
- **Dependency edges cross kinds.** A presentational component can depend on a domain component via the latter's public surface. This is the normal "I import your API" edge and works the same regardless of kind.
- **Domain-parent edges mark primary views.** They are presentational → domain, 1:N, and indicate the domain component(s) this presentational component is a *primary view* into. The semantics differ from dependency: a primary view needs to reflect what was actually built, not just the contract, which is why domain-parent edges feed fan-in synthesis (see below) while dependency edges feed only public surfaces.
- **Sibling means "same parent / same level," not "same kind."** A presentational component can have domain components as dependency siblings in the regen-prompt sense. A notifications UI component, for example, has no domain parent (notifications isn't a primary view into a single domain concept) but depends on several domain components for the data it shows.
- Admin functionality and documentation are regular features, not new node kinds. Each admin surface or doc page is a presentational feature with its own domain-parent edges where it makes sense and plain dependency edges everywhere else. No third node kind.

### Domain fan-in nodes

Domain-parent edges carry far more context than sibling dependency edges. A dependent that just imports an API only needs the public surface; a presentational node that's a primary view *into* a domain component needs to faithfully reflect what was actually built underneath, not just the contract.

To carry that load without inflating presentational regen prompts, every domain component that (a) has a presentational counterpart via a domain-parent edge and (b) has subcomponents gets a **fan-in synthesis node** sitting at the bottom of its subtree:

```
domain feature
  → domain responsibility
    → domain component (spec / contract)
      → domain subcomponents
        → subcomponent implementations
          → fan-in synthesis           ← bottom of the domain accordion
            → presentational counterpart (cross-tree, via domain_parent edge)
```

Properties:

- The fan-in is **strictly downstream** of subcomponent implementations. It synthesizes "given these subcomponent implementations, here is what this component actually exposes and does at the component level."
- It feeds **only** the presentational counterpart, via the domain-parent edge. It is never read by its own domain component, so domain regen stays single-pass top-down — no upward propagation, no two-source regen on the domain component itself.
- It is a real DAG node with its own diffs and its own staleness. When a subcomponent implementation changes, the fan-in regenerates, and *its* diff is what reaches the presentational side. The presentational node never sees N subcomponent diffs directly — its input set is bounded no matter how big the domain subtree grows.
- The presentational counterpart therefore reads two inputs from the domain subtree: the **spec** from the domain component (top-down intent) and the **fan-in** (bottom-up "what exists"). If those two ever disagree, that's a meaningful signal that the domain side has drifted from its own contract, and the presentational regen is the place where it surfaces.
- One fan-in per domain component, not one per level — the synthesis collects the entire subtree below the component in a single rollup.
- Domain components without subcomponents don't need a fan-in — their own implementation doc already is the synthesis.
- Fan-in nodes are **not reviewed directly**. They're mechanical synthesis; real edits land at the subcomponent implementations below them, and "does this reflect what was built" is actually checked at the presentational counterpart. Reviewing the fan-in itself would be triple-counting the same diff.

### Source of truth inversion

- The structured model is the source of truth.
- Documents are derived views of the model.
- Users do not edit documents directly. All writes to the model go through the LLM.
- This is the single biggest philosophical shift from v1.

---

## Propagation model

### Regen prompt context

A regen prompt for a node sees a fixed, bounded set of inputs:

- **Parent doc** — the responsibility (or component, depending on tier) the node lives under. Provides the contract the node is supposed to fulfill.
- **Related features** — the features that route through this node's subtree. Provides "what is this for, in user terms."
- **Sibling dependency APIs** — the `pubapi` fragment of every component this node depends on, pulled by fragment ID from those components' parseable architecture docs (see *Architecture documents are parseable* and *Shared fragments*). Not the full sibling docs.
- **Diffs from neighbors** — deltas from parents, children, sibling dependencies, **and** sibling dependents. Dependents matter even though their APIs are not pulled in: their diff is the signal that downstream consumers care about what this node is doing right now.

Presentational nodes additionally read the domain fan-in (see *Domain fan-in nodes*) as their input from the domain parent — both the spec and the fan-in synthesis, never the raw subtree.

This is the load-bearing scoping that keeps prompts bounded as the project grows. No node ever sees the full text of its dependencies — only their public surfaces and their diffs. No node ever sees the full implementation of its parent's other children — only what changed.

### Section-aware (fragment-level) diffs

Because architecture docs are parseable and their sections are fragments, diffs operate at fragment granularity. A change confined to `<implementation>` does not invalidate dependents that only key on the `pubapi` fragment. A change to `<public-surface>` propagates as a fragment diff to every dependent of that component. The regen prompt receives the specific fragment that changed with its before/after, rather than a whole-doc diff.

This is load-bearing: most edits during iteration are implementation-body edits, and we don't want those touching every dependent.

### Everything after initial generation is diffs

- Event-sourced history means we can always compute the delta between a node's current state and its state at the last successful generation of any neighbor.
- Regen prompts receive **deltas**, not full docs from adjacent nodes.

### Fanout decision (and why attenuation is a consequence, not a feature)

Downward propagation runs per-parent: when a parent regenerates, a **fanout decision** step determines which children to re-run given the parent's diff. In the trivial case it re-runs everything downstream. In the useful case the LLM inspects the parent diff against each child's regen prompt inputs and returns an empty set for children whose inputs didn't actually move.

This subsumes "delta attenuation": an attenuated branch is a fanout decision that returns zero children. MVP can ship with a crude fanout decision (run everything) and still be correct. Post-MVP fanout refinement is what the original delta-attenuation deferred item actually means.

### Approval gates at every hop

Restating the core principle in propagation terms: a regenerated child sits in a pending state until the user accepts it, and *its* children do not regenerate until that happens. The batched review flow walks pending nodes in topological order, and "accept" on a node is what releases propagation to that node's downstream. Until approval, the cascade halts at the edited node.

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

### Generate-parse validation

Any generation step whose output must be parseable (architecture docs, feature expansion, system architecture entries, instruction lists, change summaries) runs through a validate-retry loop. If the output fails to parse, the LLM is re-invoked with the parse error in the prompt. After N retries (configurable, default small) the node is escalated to a human review state with the last failed output and the parse errors visible.

This matters because the whole propagation model assumes parseable outputs downstream. A silently unparseable doc would either block the cascade or poison it. Human escalation on persistent parse failure is the circuit breaker.

---

## Review model

### Per-component scoping

Because each responsibility has exactly one component, we can group all diffs touching a component and review them together. **Review pass = component**, not feature, not node.

### Fan-in nodes are skipped

Domain fan-in synthesis nodes are not included in review scoping. Their role is mechanical — they exist to bound the input size of the presentational counterpart's regen prompt. Edits to them aren't meaningful; real edits land at the subcomponent implementations below them. The review pass that would otherwise "touch" a fan-in instead reviews the subcomponent implementation change that caused it.

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
- The queue is **sequential**: instructions run one at a time, in submission order, through the LLM. Concurrent execution would race on the same nodes and is not worth the implementation cost — users are not sitting there submitting hundreds of queued instructions in parallel.
- User hits "apply changes" to run regen over the queue.
- Discard the queue for a free undo of not-yet-applied changes.
- The batched review flow **is** the preview — no separate preview infrastructure needed.

### View tracking via event-log markers

The batched review UI needs to show "what this node looked like when its parent was last reviewed" for context. Naïve implementation: snapshot the world at every approval. Wasteful.

Instead, reviews are **point-in-time markers in the event log.** A view record is `(user_id, batch_id, event_offset)`. The first time a user opens a review screen for a given batch, we pin the event offset. To reconstruct what a given node looked like "at that view," we walk the event log forward from the beginning up to the pinned offset and reduce.

Properties:

- No write-time bookkeeping. Views are free to create.
- Any historical query is reconstructable from the log — "what did the user see last Tuesday?" is answerable retroactively.
- Query cost is bounded by log length up to the pinned offset. For hot review paths, snapshots can be added as an optimization without changing the data model.

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

### Rename (and every other structural edit) goes through the LLM

Every instruction in the vocabulary — including rename — runs through a regen step, not a direct model mutation. This is the same rule as "all writes to the model go through the LLM": rename is a write.

Why not let rename be a trivial DB update? Because rename interacts with content. A component's implementation doc and its dependents' prompts refer to the old name in prose. A good rename updates the prose alongside the ID alias. The LLM is the right thing to do that update; short-circuiting it means leaving stale names scattered through the docs.

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

## Code generation

Code is generated as a **leaf pass** at the bottom of the DAG, in dependency topological order. Each leaf consumes:

- Its implementation doc (the prose under the component/subcomponent)
- The `pubapi` fragments of its dependencies (same fragment-based scoping as architecture regen)
- The target language and any project-level coding conventions

Code generation is subject to the same approval gate and the same parse-validate loop: generated code must compile (or pass whatever language-specific check the project specifies) before it's considered valid. Failures escalate to human review after N retries.

The language is a project-level setting, not a framework assumption. Catapult targets Elixir. The language-agnostic public-surface format in architecture docs is what makes this viable.

### Subcomponent dependency scoping

Subcomponents are not visible outside their parent component. A subcomponent can depend on:

1. Same-parent siblings (other subcomponents of the same component), via their public surface.
2. The parent component's sibling components (i.e., other top-level components the parent depends on), via *their* public surface.

A subcomponent cannot reach into another component's subcomponents. This preserves the encapsulation the component/subcomponent split exists to provide: from outside, a component presents one public surface, and what's under it is none of a dependent's business.

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
- System architecture layer as cold-start resolver (API intent + dependency edges)
- Feature expansion as a standalone prose-iterable doc node
- Approval gates at every hop — no propagation until the edited node is accepted
- Unified DAG with domain + presentational nodes (same shape, kind tag) and domain-parent edges
- Parseable architecture docs with XML-tagged sections and language-agnostic fenced code
- Shared-fragment transclusion for public/private/dependency sections with fragment IDs
- Section-aware (fragment-level) diffs
- Domain fan-in synthesis nodes feeding presentational counterparts (skipped in review)
- Bounded regen-prompt context (parent doc, related features, sibling API fragments, neighbor diffs)
- Crude fanout decision per parent (no-op attenuation is correct, refinement is post-MVP)
- Generate-parse validation with retry-then-escalate for all parseable outputs
- Change summaries as part of generation
- Per-component review scoping with fan-in skip
- View tracking via event-log markers
- Read-only generated views with tags displayed verbatim
- All six structured UIs with create + promotion/demotion
- Prose feedback on all nodes
- Full instruction vocabulary with stable-ID lineage references (IDs in `<kind>_<8 chars>` form)
- Sequential pending-change queue with batched review
- Code generation as a leaf pass in dependency topo order

**Deferred post-MVP:**
- Fanout decision refinement (the optimization the old "delta attenuation" bullet described)
- Vector search review augmentation (nice safety net, not load-bearing)
- Two-pass upward propagation automation (manual "regen children from here" button works for MVP)
- Auto-propagation (explicit regen buttons for MVP; auto comes once regen quality is trusted)
- View-history snapshot optimization (log-walk is fine until profiling says otherwise)

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
- Mechanism for minting the 8-char Crockford ID suffixes and detecting collisions (random + retry, or counter-based?)
- How the feature expansion's "approve to mint feature nodes" step reconciles with later edits that change feature boundaries (does re-approval re-mint, or is there a reparse-diff step?)
- Where change summaries live in the event stream vs. a separate log
- Multi-user concurrency on the pending-change queue (MVP assumes single-user-at-a-time per project; revisit if that's wrong)
- How deep the crude fanout decision can be before it becomes a bottleneck worth refining
- Review-UI presentation of fragment diffs vs. whole-doc diffs
- Mobile-specific interaction details for the graph editors
