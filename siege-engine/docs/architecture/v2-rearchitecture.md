# SiegeEngine v2 Architecture

Living design doc for the v2 rewrite. Captures the structured-model rearchitecture discussion. This is the target architecture, not the current state of the code — the current code will be gutted before v2 is built.

---

## Problem statement

In v1, most changes have to propagate from the system level down. This makes system-level docs grow without bound and undermines the benefit of breaking work into smaller chunks. The underlying cause is that documents are the source of truth and the DAG is a linear-ish chain of ever-more-specific docs derived from a single god doc. There's no good way to make a localized change without touching everything upstream of it.

v2 inverts this: a **structured model** is the source of truth, documents are **derived views** of the model, and changes propagate as **diffs** through a unified DAG in both directions.

---

## Core principle: approval gates destructive operations

A change to a node propagates to its neighbors as soon as the change exists, with one carve-out: **operations that would destroy or reshape content downstream are gated on explicit user approval of the originating node.** Everything else propagates immediately.

The reason for the carve-out is asymmetry. Most edits — public-surface changes, implementation tweaks, dependency-edge edits, renames, reparenting, promotion/demotion — are reversible. Content carries forward through regen via lineage references (see *Instruction vocabulary*), prior versions live in the event log, and a regen the user doesn't like can be rolled back by walking the log. The worst case of a "wrong" non-destructive cascade is some redundant LLM work and the inconvenience of reviewing the result. No user prose is lost.

Destructive operations are different. They include:

- **Delete** — cascading to children would lose all their content with no recovery short of replaying the event log to a prior offset.
- **Merge** — reconciling overlapping content forces the LLM to drop or summarize material, and the dropped pieces can be exactly the prose the user has been iterating on.
- **Split** — distributing one source across multiple destinations has the same loss profile.

These three gate. Everything else runs. The gate exists specifically to prevent unrecoverable content loss, not to make the user babysit every cascade. Without this narrowing the original "gate everything" rule would block even obviously-safe edits and train the user to click through without reading, which defeats the point.

Corollary: a node's *initial mint* (e.g. minting responsibility/component nodes from an approved sysarch, or minting feature nodes from an approved expansion) is treated as destructive at the child level — the mint commits to a particular shape, and if the user wants a different shape, the mint is the moment to catch that. After the mint, edits to the minted children propagate normally.

The pending-change queue and batched review flow are how gated changes are presented when the gate fires. Non-destructive changes also flow through the queue (it's how multi-instruction edits batch into one apply), but they don't halt at the user's attention.

---

## Data model

### Generation order and the system architecture layer

The cold start — building a project from an input doc — runs through a fixed topological order. Each layer is a node (or set of nodes) with its own prose, its own approvals, its own regen prompt:

1. **Input doc** — the raw prose the user brings in. The only node the user authors directly.
2. **Feature expansion** — a prose decomposition of the input into features, iterated on as a standalone document node *before* any feature nodes exist. Approving the expansion is what mints (or updates) the individual feature nodes downstream.
3. **System architecture (two passes, one node)** — the cold-start resolver: a singleton `sysarch` node that gets generated in two stages.
   - **Pass A: features → responsibilities.** Each feature decomposes into responsibilities. Local reasoning, low cross-talk, easy to review. Produces the responsibilities-only section of the sysarch doc.
   - **Pass B: responsibilities → components + dep edges + domain-parent edges + API intent + system-level technical specification.** Single LLM call. These are mutually informing — component boundaries are justified by the APIs they expose and the dep edges they avoid, so picking boundaries before APIs leads to bad boundaries. Pass B fills out the rest of the sysarch doc.
   - Both passes are regens of the same sysarch node. Pass B consumes pass A's approved output.
4. **Component architecture docs** — generated in dependency topological order. Each consumes the system architecture's entry for it (including its intended API) plus the public surfaces of its dependencies.
5. **Subcomponent architecture docs** — generated in dependency topological order within each component.
6. **Implementation docs** — separate leaf nodes (`impl_*`) hanging off each subcomponent and each un-fanned-out component. Carry the actual design and build details for that leaf, distinct from the parent's high-level technical specification.
7. **Plan nodes** — single-use, per-impl planning artifacts that translate an impl edit into a concrete list of code changes (see *Plan nodes*). Generated whenever an impl node changes; consumed by the next code-gen pass.
8. **Code** — generated as a final leaf pass, plan by plan, in dependency topological order.

The system architecture resolves the chicken-and-egg of "component A's regen needs component B's public surface, but B hasn't been generated yet" by committing to API intent up front. Component archs then flesh the intent into full public-surface detail, and the system architecture's API entry for each component is a transcluded fragment of the component arch (see *Shared fragments*) — so drift between "what we said" and "what got built" is detectable as a fragment diff.

**Cold-start vs incremental sysarch are different prompts.** The cold-start prompt expects the full feature set and produces everything from scratch. Adding a feature later runs an incremental-add prompt that takes the existing sysarch plus the one new feature and produces a delta. Treating them as the same template with different inputs produces a prompt that hedges badly on both jobs. Two prompts, one job handler that picks which. The MVP scaling assumption is that the initial feature set fits in context and subsequent feature additions are rare.

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

Component and subcomponent architecture docs are not free-form prose. They have a stable section structure the model can parse, because sibling components' regen prompts pull each others' API surfaces out of these docs and stuffing the entire dependency doc into every dependent's prompt would blow up context.

Required sections, each wrapped in an XML tag:

- `<technical-specification>` — the high-level "what are we building and with what" for this component: technologies, major algorithmic choices, cross-cutting invariants. Deliberately abstract — no responsibility assignments, no per-subcomponent sequencing. Its job is to let the LLM *think* about the shape of the thing before it decomposes. A change to a child's implementation does **not** regenerate the tech spec; the spec propagates downward, not upward.
- `<public-surface>` — the component's API. Types, function signatures, methods, events — anything a dependent is allowed to reach for. This is what gets extracted and handed to dependents at regen time.
- `<private-surface>` — internal types and helpers. Visible to the component's own subcomponents during their regen, but not to sibling dependents.
- `<dependencies>` — the list of sibling components this one reaches for, by stable ID. Parseable separately because it feeds dependency-edge edits and cycle detection.

The system architecture node has its own `<technical-specification>` section at the top-level tier, where project-wide concerns like language choice and runtime targets live. Subordinate tech specs inherit those constraints; child tech specs are allowed to narrow the parent's choices but not contradict them.

Note that the actual detailed implementation prose for a leaf — behavior, invariants, sequencing, edge cases — does **not** live inside the component arch doc. It lives in a separate `impl_*` leaf node hanging beneath each subcomponent or un-fanned-out component (see *Implementation nodes*). Splitting these apart is what keeps a child's iteration from constantly re-thrashing the parent's tech spec.

Inside `<public-surface>` and `<private-surface>`, code-shaped content lives in language-agnostic fenced code blocks. The parser doesn't inspect the code — it just pulls the tagged section whole. This matters because Catapult (v2's first real project) is written in Elixir, and the parser must not care what's inside the fences.

**Tags are displayed, not stripped.** User-facing rendering of architecture docs keeps the XML tags visible. SiegeEngine's audience is technical; a "stored vs shown" transform would only add bugs without adding clarity.

The public/private split is real architectural work the LLM does at authoring time, not a post-hoc tagging pass. A wrong export decision propagates as silent context loss to every dependent, so the public-surface section is itself a reviewable artifact — surfaced as a derived view on the component, and probably promoted to one of the structured UIs if the export decisions turn out to be a frequent source of feedback.

### Shared fragments (transclusion)

Some content belongs to more than one node. The most important case: a component's public surface is both part of that component's architecture doc *and* part of the system architecture's entry for it. Duplicating the content guarantees drift. Instead, each parseable section is a **fragment** with its own stable ID, and both docs transclude it.

Fragment ID format: `<owner_id>_<fragment_kind>`. The fragment kind vocabulary is fixed:

- `techspec` — the `<technical-specification>` section
- `pubapi` — the `<public-surface>` section
- `privapi` — the `<private-surface>` section
- `deps` — the `<dependencies>` section

Example: `comp_a3f7k2m9_pubapi` is the public surface fragment owned by component `comp_a3f7k2m9`. The parser splits on the last underscore; `<owner_id>` is stable and opaque (see *ID scheme*), `<fragment_kind>` is validated against the vocabulary.

**Fragment kinds are required to be single-token** — no underscores inside a kind name — so the last-underscore split rule is unambiguous. Enforced at the parser and asserted when a new kind is added to the vocabulary.

Properties:

- **Fragments don't move.** They're tied to their owner. Merge/split of an owning component cascades to its fragments automatically.
- **Diffs operate on fragments, not whole docs.** When a component's public surface changes, the fragment's diff is what propagates. Dependents key on the fragment ID, so a change confined to `<technical-specification>` or to a child `impl_*` node doesn't invalidate dependents that only read the `pubapi` fragment.
- **Disagreement detection is a fragment diff.** If the system architecture claimed a component would expose one API and the component arch ended up exposing a different one, the system architecture's copy of `comp_X_pubapi` and the component arch's copy diverge. That's the drift signal, surfaced naturally.

### ID scheme

Every entity in the model gets a stable ID of the form `<kind>_<8 base32 Crockford chars>`, e.g. `comp_c5h9m4p1`, `feat_bqr3t8wv`, `resp_k2p7xn4m`.

Kind vocabulary:

- `feat` — feature
- `resp` — responsibility
- `comp` — component (tier-agnostic: top-level components and subcomponents both use `comp_`, because promotion/demotion between tiers must not change the ID)
- `impl` — implementation node (leaf under a subcomponent or un-fanned-out component)
- `plan` — single-use plan node between `impl` and code generation (see *Plan nodes*)
- `edge` — dependency or domain-parent edge, when edges need their own identity
- `expansion` — the per-project singleton feature expansion node
- `sysarch` — the per-project singleton system architecture node
- `fanin` — a domain fan-in synthesis node (one per domain component with subcomponents)

Fragment IDs extend this as described above.

Singletons (`expansion`, `sysarch`) still use the `<kind>_<8 chars>` form for consistency even though the suffix is decorative for a one-per-project node. Uniform IDs mean uniform fragment keys, uniform lookup, no special cases at call sites.

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

To carry that load without inflating presentational regen prompts, **every domain component with subcomponents gets a fan-in synthesis node**, sitting at the bottom of its subtree, regardless of whether a presentational counterpart currently exists. Always-minting is a deliberate simplification: it means adding a domain-parent edge later never has to retroactively materialize a fan-in, and the minting rule is purely a function of the domain subtree shape. The cost is a few extra regens for fan-ins nobody is reading yet, which is acceptable.

Domain components without subcomponents don't need one — their own implementation node already is the synthesis, and the presentational counterpart (if any) reads it directly.

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
- It feeds **only** presentational counterparts (current or future), via domain-parent edges. It is never read by its own domain component, so domain regen stays single-pass top-down — no upward propagation, no two-source regen on the domain component itself.
- It is a real DAG node with its own diffs and its own staleness. When a subcomponent implementation changes, the fan-in regenerates, and *its* diff is what reaches the presentational side. A presentational node reading it never sees N subcomponent diffs directly — its input set is bounded no matter how big the domain subtree grows.
- A presentational counterpart reads two inputs from the domain subtree: the **spec** from the domain component (top-down intent) and the **fan-in** (bottom-up "what exists"). If those two ever disagree, that's a meaningful signal that the domain side has drifted from its own contract, and the presentational regen is the place where it surfaces.
- One fan-in per domain component, not one per level — the synthesis collects the entire subtree below the component in a single rollup.
- Fan-ins are minted unconditionally for any domain component with subcomponents, even ones that don't yet have a presentational counterpart. Always-present fan-ins mean adding a domain-parent edge later is a pure edit, not a mint-on-the-fly.
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

Because architecture docs are parseable and their sections are fragments, diffs operate at fragment granularity. A change confined to `<technical-specification>` does not invalidate dependents that only key on the `pubapi` fragment. A change to `<public-surface>` propagates as a fragment diff to every dependent of that component. The regen prompt receives the specific fragment that changed with its before/after, rather than a whole-doc diff. Implementation prose edits live in child `impl_*` nodes entirely, so they never show up as diffs on the parent component arch doc at all.

This is load-bearing: most edits during iteration are impl-node edits, and we don't want those touching every dependent of the parent component.

### Everything after initial generation is diffs

- Event-sourced history means we can always compute the delta between a node's current state and its state at the last successful generation of any neighbor.
- Regen prompts receive **deltas**, not full docs from adjacent nodes.

### Fanout decision (and why attenuation is a consequence, not a feature)

Downward propagation runs per-parent: when a parent regenerates, a **fanout decision** step determines which children to re-run given the parent's diff. In the trivial case it re-runs everything downstream. In the useful case the LLM inspects the parent diff against each child's regen prompt inputs and returns an empty set for children whose inputs didn't actually move.

This subsumes "delta attenuation": an attenuated branch is a fanout decision that returns zero children. MVP can ship with a crude fanout decision (run everything) and still be correct. Post-MVP fanout refinement is what the original delta-attenuation deferred item actually means.

### Approval gates at destructive hops only

Restating the core principle in propagation terms: a regenerated child propagates immediately to *its* children unless the regen is destructive at the grandchild level. Non-destructive cascades run freely through the DAG and land in the batched review flow for inspection, not for blocking permission. Destructive cascades — delete, merge, split — halt at the originating node until the user explicitly approves them, because that's the only class of operation where content is unrecoverable.

"Accept" in the review UI for non-destructive changes means "I've looked at this, it's fine" (informational). For destructive changes it means "permission to destroy" (blocking). The UI surfaces the distinction so the user knows which ones actually need their attention and which ones are routine.

### Bi-directional regeneration

- **Downward:** follow dependency edges, regenerate children with parent deltas.
- **Upward (two-pass, post-MVP):** walk up through parents to the system level, then flip and walk back down through all children of touched parents. Generation at fanout boundaries decides which children to regenerate — not a blanket "regen everything downstream."

### Auto-propagation and batched review

Under the destructive-gate model, non-destructive propagation runs automatically — a regen's output flows into its non-destructive downstream without waiting for per-hop approval. MVP ships this behavior; the thing deferred post-MVP is the *polished* combined-navigable-diff UI that presents the results.

- Propagation runs automatically after any non-destructive edit.
- Destructive edits (delete / merge / split) halt at the originating node until explicitly approved.
- The batched review flow is how the user sees what changed. MVP uses a simple per-component walk; post-MVP adds the combined navigable diff and version-dropdown navigation on each node so you can see "what this node looked like when its parent was last reviewed."

### Change summaries

- Generated as part of the generation step — the LLM appends a change summary section to its output.
- Stripped before storage but captured into a structured change log.
- Becomes queryable audit history for free, and feeds the vector-search index.

### Generate-parse validation

Any generation step whose output must be parseable (architecture docs, feature expansion, system architecture entries, instruction lists, change summaries) runs through a validate-retry loop. If the output fails to parse, the LLM is re-invoked with the parse error in the prompt. After N retries (configurable, default small) the node is escalated to a human review state with the last failed output and the parse errors visible.

This matters because the whole propagation model assumes parseable outputs downstream. A silently unparseable doc would either block the cascade or poison it. Human escalation on persistent parse failure is the circuit breaker.

### Generation telemetry

Every LLM call records its token usage, keyed by `(node_id, fragment_or_section, model, prompt_tokens, completion_tokens, timestamp)`. This data is not part of the event log — it's observability, not state — but it **is** surfaced in the UI alongside the artifacts it belongs to:

- Every node and every parseable section displays its most recent generation's token count in-place. No digging through logs.
- The batched review UI shows aggregate token usage for the whole batch so the user can see "this review pass cost X tokens" at a glance.
- Per-project and per-component rollups are queryable from the debug/projection endpoint.

The point is not cost discipline for the MVP (we've accepted we won't be optimizing cost yet). The point is making runaway prompt growth immediately visible. A regen that suddenly costs 5x what it cost yesterday is the signal that something is wrong with the prompt — too much sibling context, an uncontrolled dependency fan-out, a prompt template regression — and we want that signal visible at the UI the moment it happens, not after somebody bothers to look at a log.

Telemetry is written synchronously with each LLM call as part of the job handler. Missing telemetry is treated as a generation failure for alerting purposes even though it doesn't fail the generation itself.

---

## Review model

### Per-component scoping

Because each responsibility has exactly one component, we can group all diffs touching a component and review them together. **Review pass = component**, not feature, not node.

### Fan-in nodes are skipped

Domain fan-in synthesis nodes are not included in review scoping. Their role is mechanical — they exist to bound the input size of the presentational counterpart's regen prompt. Edits to them aren't meaningful; real edits land at the subcomponent implementations below them. The review pass that would otherwise "touch" a fan-in instead reviews the subcomponent implementation change that caused it.

### Vector search as safety net (post-MVP)

- Embed: implementation nodes, responsibility descriptions, API definitions, change summaries.
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

Why not let rename be a trivial DB update? Because rename interacts with content. A component's architecture doc and its dependents' prompts refer to the old name in prose. A good rename updates the prose alongside the ID alias. The LLM is the right thing to do that update; short-circuiting it means leaving stale names scattered through the docs.

### Lineage preservation

Every structural operation that changes identity (rename, promote, reparent, merge, split) must carry lineage references. Without them, regen starts fresh and throws away prose the user has been iterating on.

Example prose instructions (bulleted, with stable IDs):

> - Rename component `comp_auth_svc_abc123` to "IdentityService" (preserve existing content)
> - Promote subcomponent `subcomp_token_store_def456` under `comp_auth_svc_abc123` to a top-level component (preserve existing content and responsibilities)
> - Merge components `comp_auth_svc_abc123` and `comp_id_svc_xyz789` into a single component named "IdentityService" (reconcile overlapping content, prefer `comp_auth_svc_abc123` for conflicts)

The LLM sees both: the name for intent, the ID for lineage. Regen prompts then say "here is the previous architecture doc for `comp_auth_svc_abc123`, produce the new version for `IdentityService` incorporating these changes," and content carries forward naturally.

### LLM has leeway

Instructions are **directives, not mutations**. "The user wants X in Y, figure out how to make that coherent" rather than "set X.component = Y". If a user moves something somewhere it doesn't fit, the LLM has latitude to restructure the destination, push back, or split the incoming thing.

---

## Implementation nodes

An **implementation node** (`impl_*`) is a leaf that hangs off every subcomponent and every un-fanned-out component. It carries the actual design-and-build details for that leaf: behavior, invariants, sequencing, edge cases, the stuff that used to live in `<implementation>` back when the architecture doc had one. It is deliberately separate from the parent's technical specification so that child iteration doesn't re-thrash the parent's high-level choices.

Properties:

- **One per leaf.** Each subcomponent has exactly one `impl_*` child. A component with subcomponents has no impl node of its own — its impl lives in its subcomponents' impl nodes. A component with no subcomponents (an "un-fanned-out component") has one directly.
- **Reads from two places.** Parent component's `techspec` and `pubapi`/`privapi` fragments, plus the `pubapi` fragments of its dependencies. Same fragment-based scoping as architecture regen.
- **Feeds plan generation.** Code is not generated directly from impl nodes (see *Plan nodes*). Changes to an impl node produce a fresh plan node downstream.
- **Gate on destructive edits only**, like everything else.

## Plan nodes

Code generation does not consume implementation nodes directly. Each impl change produces a **plan node** — a single-use, reviewable artifact that translates the impl edit into a concrete list of code changes. Code generation then consumes the plan, not the impl.

Why split the LLM call? Because this is the single most user-relevant gate point in the whole system. Generating code in one monolithic "read the impl, think, write code" call gives the user nowhere to intervene before files start moving. Splitting it into plan-then-execute makes the LLM's reasoning a reviewable artifact and gives the user a place to say "no, don't do it that way" before any code is touched.

Properties:

- **Single-use.** A plan is generated for one impl change and consumed by one code-gen pass. The next impl change generates a new plan. Old plans stay in the event log for audit; only one plan is "live" per impl at a time, via a current-pointer on the impl node.
- **Reviewable and independently gated.** Approving an impl edit is permission to generate a plan; approving the plan is permission to write code. An impl approval never silently authorizes code mutations.
- **Per-impl, per-change, dep-topo order.** Plans are generated in dependency topological order. Each plan can read prior plans + their generated code from earlier in the same batch, so cross-impl coherence falls out for free.
- **Structured output.** The plan prompt takes (current impl node, prior impl node, dep `pubapi` fragments, project language settings) and produces a list of (file, region, change) tuples plus a prose explanation of why. The structured list is what code-gen consumes; the prose is what the user reviews.
- **Parse-validate loop applies.** If the plan fails to parse, retry-then-escalate, same as any other parseable output.

## Code generation

Code is generated as a **leaf pass** at the bottom of the DAG, in dependency topological order, one plan at a time. Each plan-execution call consumes:

- Its plan node (the (file, region, change) tuples)
- The `pubapi` fragments of its dependencies (same fragment-based scoping as architecture regen)
- The target language and any project-level coding conventions (inherited from the sysarch `techspec`)

Code generation is subject to the parse-validate loop: generated code must compile (or pass whatever language-specific check the project specifies) before it's considered valid. Failures escalate to human review after N retries. Once code is generated, the plan node is considered consumed; the event log keeps it for audit.

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
- Structured model (features, responsibilities, components, subcomponents, implementations) as source of truth
- Feature expansion as a standalone prose-iterable doc node
- System architecture as a singleton two-pass cold-start resolver (Pass A: features → responsibilities; Pass B: responsibilities → components + APIs + dep edges + domain-parent edges + system-level techspec)
- Separate cold-start vs incremental-add sysarch prompts
- Approval gates **narrowed to destructive operations** (delete, merge, split); non-destructive changes propagate automatically
- Unified DAG with domain + presentational nodes (same shape, kind tag) and domain-parent edges
- Parseable architecture docs with XML-tagged sections (`<technical-specification>`, `<public-surface>`, `<private-surface>`, `<dependencies>`) and language-agnostic fenced code
- Shared-fragment transclusion with fragment IDs (`techspec`, `pubapi`, `privapi`, `deps`), fragment kinds required to be single-token
- Section-aware (fragment-level) diffs, implemented as a shared regen helper from the start (not retrofitted)
- Implementation nodes (`impl_*`) as separate leaf nodes under every subcomponent and un-fanned-out component
- Always-mint domain fan-in synthesis nodes for every domain component with subcomponents (skipped in review)
- Plan nodes (`plan_*`) between impl and code — single-use, independently gated, one-live-per-impl
- Bounded regen-prompt context (parent doc, related features, sibling API fragments, neighbor diffs)
- Crude fanout decision per parent (no-op attenuation is correct, refinement is post-MVP)
- Generate-parse validation with retry-then-escalate for all parseable outputs
- Change summaries as part of generation
- Generation telemetry surfaced in the UI (per-node, per-section, per-batch token counts)
- Per-component review scoping with fan-in skip
- View tracking via event-log markers, with review-screen snapshot cache from day one
- Read-only generated views with tags displayed verbatim
- All six structured UIs with create + promotion/demotion
- Prose feedback on all nodes
- Full instruction vocabulary with stable-ID lineage references (IDs in `<kind>_<8 chars>` form; singleton kinds included)
- Sequential pending-change queue with batched review
- Code generation as a plan-driven leaf pass in dependency topo order

**Deferred post-MVP:**
- Fanout decision refinement (the optimization the old "delta attenuation" bullet described)
- Vector search review augmentation (nice safety net, not load-bearing)
- Two-pass upward propagation automation (manual "regen children from here" button works for MVP)
- Polished combined-navigable-diff review UI (MVP ships a simple per-component walk)
- View-history snapshot optimization beyond the basic review cache (fine until profiling says otherwise)

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
- How sysarch Pass A and Pass B coordinate on re-approval — does a pass B edit ever need to re-run pass A?
- Granularity of the `impl` → `plan` → code mapping: one code unit per plan, or can a plan span multiple files / modules? Implications for plan-approval UX.
- Whether plan nodes should be re-generatable with feedback (like other nodes) or strictly re-minted on impl change
- Exact UI treatment for the destructive-vs-non-destructive gate distinction so users learn the difference quickly
- Where change summaries live in the event stream vs. a separate log
- Where generation telemetry lives (side table, event-log metadata, or both)
- Multi-user concurrency on the pending-change queue (MVP assumes single-user-at-a-time per project; revisit if that's wrong)
- How deep the crude fanout decision can be before it becomes a bottleneck worth refining
- Review-UI presentation of fragment diffs vs. whole-doc diffs
- Mobile-specific interaction details for the graph editors
