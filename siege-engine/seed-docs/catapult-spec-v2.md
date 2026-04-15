# Catapult — Specification (v2)

## Vision

Catapult is a **design memory** system. It is not just a documentation tool and not just a code generator — it is the machine that holds the *why* behind every architectural decision, the *shape* of every component boundary, and the *history* of every revision. When an AI generates code, it does so informed by the full context of human decisions that preceded it. When a human reviews output, they see exactly where it sits in the design hierarchy and what upstream thinking produced it.

The core insight is that AI-generated code is only as good as the design thinking that guides it. A single massive prompt produces generic output. A structured graph of design entities — features feeding responsibilities feeding component architectures feeding plans feeding code — produces code that reflects genuine design intent. Catapult maintains this graph as a living artifact: event-sourced, reviewable, and always the authoritative source of truth for what the system is and why it was built that way.

This makes Catapult a *plan-before-you-code* machine. The design graph isn't scaffolding to be discarded after generation — it is the persistent design memory of the project. Changes flow through it: new features are routed to the right components, bug fixes propagate upward from affected code, refinements cascade through dependent nodes. The structured model evolves with the codebase because it *is* the codebase's design substrate.

For teams, this means onboarding becomes reading the graph. Architectural disputes become conversations anchored to specific nodes. Code review starts with design review. The system doesn't just generate — it remembers, and it holds teams accountable to their own design decisions.

---

Catapult is the industrial-strength successor to Siege Engine. It is an AI-powered design and code generation system that takes a project description and produces a complete structured model of the system and the code that implements it, through a reviewable pipeline.

The central design commitment: the **structured model is the source of truth**. Documents are *derived views* of the model. Users never edit document text directly — every write goes through the LLM via prose feedback, regeneration, and approval. The model is event-sourced; the current state is a projection of that event log; rebuilding the projection from the log must reproduce the same state byte-for-byte.

This specification is divided into two parts: **A. Requirements** (what the system does) and **B. Architecture** (what technologies are used and how). It describes the target design; it does not describe migration from any particular current state.

---

# Part A — Requirements

## A.1 Core concepts

### A.1.1 Structured model as source of truth

The structured model is a graph of typed nodes and typed edges, stored in a relational database as the projected result of an append-only event log. The current state of any node is a function of the events applied to it; rebuilding the projection from the log must reproduce the current state byte-for-byte, and this invariant is tested exhaustively.

Users do not edit nodes directly. There is no text field anywhere in the UI that lets a user type characters into a generated document and have those characters become the stored content. Every write to the model goes through the LLM via a **prose feedback → regenerate → approve** cycle. The one exception is a small set of structured UIs (drag-drop assignment pages, graph editors for edges, dependency editors) that handle structural operations that are miserable to express in prose — and even those produce **prose instructions** that flow through the regeneration pipeline on "apply changes," not direct state mutations.

All writes go through a single reducer entrypoint that validates the event, appends it to the log, and applies the projection delta in one transaction. There are no duplicate-status fields on parallel tables that can drift out of sync with the event log — the projection is the only place state lives, and reverting a node is "append events that undo the prior delta," never "reach into a table and change a row."

Documents, diffs, rendered architecture pages, review artifacts — everything the user sees — are **derived views** of the model. They are re-computable from the event log at any point in history. This is the single biggest philosophical shift from v1: the document was never the real artifact; it was always just a way of looking at the underlying decisions.

### A.1.2 Node tier vocabulary

The model has a small closed vocabulary of node tiers. Each tier represents a distinct kind of design entity and has its own generation prompt, its own review surface, and its own place in the cold-start ordering (A.3.1).

- **`feat`** — a feature. The unit a user thinks in ("billing," "collaborative editing"). Features are slices, not containers — a single feature can implicate many components. Minted from an approved feature expansion.
- **`resp`** — a responsibility. Features decompose into responsibilities via many-to-many decomposition edges. The `resp` tier is tier-agnostic *for ID purposes*: top-level responsibilities (minted by the requirements bootstrap) and per-component subresponsibilities (minted by each component's subrequirements bootstrap) both use the `resp_` prefix because promotion/demotion between tiers must not change the ID. The tier split lives in the nodes' parent assignments, not in the kind.
- **`comp`** — a component. Each top-level responsibility maps to exactly one component (many-to-one). The `comp` tier is also tier-agnostic *for ID purposes*: top-level components and subcomponents both use the `comp_` prefix for the same promotion/demotion reason. The structural tree is hard-capped at two component levels — see A.1.7.
- **`policy`** — an enforced-usage policy. A constraint rather than a capability: "every LLM call records telemetry," "every DB write goes through the reducer." Carries a trigger phrase, a required responsibility, and a rationale. Minted from the `<policies>` section of a system or component architecture doc. See A.1.10.
- **`impl`** — an implementation node. A leaf hanging off each subcomponent and each un-fanned-out component. Carries the detailed design and build content that the component architecture doc deliberately abstracts away. Maps to a folder on disk via the file manifest (A.1.11).
- **`plan`** — a per-impl plan node. Translates an impl-level intent into a concrete list of code changes. Reviewed with prose feedback like any other node; consumed by the next code-gen pass once approved.
- **`expansion`** — the per-project singleton feature expansion bootstrap node. Holds the prose decomposition of the raw input into features before any feature nodes exist. Read-only after initial approval.
- **`reqs`** — the per-project singleton top-level requirements bootstrap node. Decomposes the approved feature set into top-level responsibilities. Read-only after initial approval.
- **`sysarch`** — the per-project singleton system architecture bootstrap node. Takes the top-level responsibilities and produces the component graph: components, API intent, top-level policies, dep edges, domain-parent edges, and a system-level technical specification. Read-only after initial approval.
- **`subreqs`** — a per-top-level-component subrequirements bootstrap node. Decomposes the component's assigned top-level responsibilities into its subresponsibilities. One per top-level `comp_*`, minted at sysarch approval. Read-only after initial approval.
- **`manifest`** — the per-project singleton file territory manifest. Maps every folder in the repository to an owning `impl_*` leaf. See A.1.11.
- **`fanin`** — a domain fan-in synthesis node. One per domain component with subcomponents. Synthesizes the full subtree below a domain component into a single rollup that presentational counterparts read via domain-parent edges. See A.1.9.
- **`changeplan`** — a change-plan node. Minted per flow run per affected tier to describe "what this change means at this tier" as a reviewable prose artifact before the regen commits. Goes through the same draft → review → approve lifecycle as bootstrap nodes but does not project structured children and does not live in the dependency graph. Persists in the event log as provenance — see A.4.3.
- **`vocab`** — a project-specific term with its definition and optional cross-references. Scoped via `parent_id`: `null` for project-level terms, a `feat_*` id for terms introduced by and meaningful inside a single feature's subtree. Content is a parseable `<vocab-entry>` XML block matching the same parseable-tier family as comparch and subcomparch. Minted from the `<vocabulary>` section of the expansion bootstrap, editable via the instruction vocabulary and the normal draft → feedback → approve loop. See A.1.12.

Every node kind has a `kind` field distinguishing **`domain`** from **`presentational`**. Admin surfaces, documentation pages, and UI features are regular presentational nodes — there is no third node kind, and nothing special-cases them.

### A.1.3 Edge type vocabulary

Every edge in the model carries a typed `edge_type` plus a source node ID and a target node ID. The vocabulary is closed — any new edge kind requires a reducer change and a migration, which is intentional because silently introducing edge types that existing projection logic ignores is a recipe for drift.

- **`dependency`** — `comp_* → comp_*`. "A depends on B": A's public surface reaches into B's public surface. Emitted by the system architecture and component architecture passes in each arch doc's `<dependencies>` section. Policy-induced dependency edges (see A.1.10) are emitted alongside, at the same time as the policies that imply them, so that policy-induced edges land naturally in the same pass rather than being backfilled later.
- **`domain_parent`** — `comp_* → comp_*` (presentational → domain, 1:N). "This presentational component is a primary view into this domain component." Semantics differ from a plain dependency: a primary view needs to reflect what was *built*, not just the API contract, so domain-parent edges feed fan-in synthesis nodes instead of public-surface fragments. A presentational component can have multiple domain parents, and a domain component can have multiple presentational counterparts.
- **`policy_application`** — `policy_* → comp_*`. "This policy applies to this component at these trigger sites." Emitted by the component-architecture pass when a component is generated, not at policy mint time, because applicability is a decision that needs the target component's full techspec and subresponsibilities as input — information that doesn't exist yet at sysarch approval. See A.1.10.
- **`decomposition`** — many-to-many projection edges. Two conventions share the type:
  - `feat_* → resp_*`: the feature implicates the top-level responsibility. Emitted at requirements-mint time.
  - `resp_* → resp_*` (top-level → subresp): the top-level responsibility decomposes into the subresp within the subresp's owning component. Emitted at subrequirements-mint time. Both endpoints use the tier-agnostic `resp_*` prefix; the tier split lives in the nodes' parent assignments.

Edges are never authored by direct user action. They are minted by passes that approve a projection source, and edited via the instruction vocabulary (renames, reparents, promotes, demotes, merges, splits, plus the per-edge-type create/delete operations), which emit events that the reducer projects into edge mutations. The instruction vocabulary is how structural edits happen; direct row mutation is never an option.

Cycle detection for dependency edges runs at every edge-create and at every mint pass. A proposed edge that would close a cycle is rejected before it's applied, and the prompt renders the rejection back to the LLM on retry.

### A.1.4 ID scheme

Every entity in the model carries a stable ID of the form `<kind>_<8 Crockford base32 chars>`: `comp_c5h9m4p1`, `feat_bqr3t8wv`, `resp_k2p7xn4m`. The suffix is fully opaque — it is not derived from the entity's name, because rename must not change identity and a slug-based ID would force either renaming the ID (breaks lineage) or letting the ID lie about the current name.

Names are always carried alongside IDs in prose instructions, regeneration prompts, and the UI. The ID is for lineage; the name is for intent; the LLM sees both. Lineage across rename / promote / demote / reparent / merge / split is tracked in the event log, not encoded in the ID. An ID is stable for the lifetime of an entity and gone when the entity is deleted; IDs are never reused.

Singletons (`expansion`, `reqs`, `sysarch`, `manifest`) use the same `<kind>_<8 chars>` form as non-singletons, even though the suffix is decorative for a one-per-project node. Uniform IDs mean uniform fragment keys, uniform lookup tables, and no special cases at call sites. `subreqs_*`, `changeplan_*`, and `fanin_*` are *not* singletons — there is one per top-level component for subreqs, one per flow-run per affected tier for change plans, and one per domain component with subcomponents for fan-ins — so the suffix is load-bearing for them and the same form applies uniformly.

**Bootstrap-vs-child naming convention.** Bootstrap nodes (`expansion_*`, `reqs_*`, `sysarch_*`, `subreqs_*`) are named after the prose *document form* they carry before approval — feature expansion, requirements, system architecture, subrequirements. The structured children each bootstrap mints are named after their *semantic role* in the model — `feat_*` for features, `resp_*` for responsibilities, `comp_*` for components. The two vocabularies are deliberately distinct because they refer to different things: the document form describes the prose artifact the user reviews and approves, while the child kind describes the structured unit in the model that results.

### A.1.5 Fragments and transclusion

Component and subcomponent architecture documents are not free-form prose. They have a stable section structure the model can parse, because sibling components' regeneration prompts pull each other's API surfaces out of these docs at context-assembly time, and stuffing the entire dependency doc into every dependent's prompt would blow up the context budget as the project grows.

Required sections, each wrapped in an XML tag, **in this order**:

- `<technical-specification>` — the high-level "what are we building and with what" for this component: technologies, major algorithmic choices, cross-cutting invariants. Deliberately abstract — no responsibility assignments, no per-subcomponent sequencing. Its job is to let the LLM *think* about the shape of the thing before it decomposes. A change to a child's implementation does **not** regenerate the techspec; the spec propagates downward, not upward.
- `<public-surface>` — the component's API. Types, function signatures, methods, events — anything a dependent is allowed to reach for. This is what gets extracted and handed to dependents at regen time.
- `<private-surface>` — internal types and helpers. Visible to the component's own subcomponents during their regen, but not to sibling dependents.
- `<policies>` — the policies this arch doc mints, each a structured tuple of trigger + required responsibility + rationale. Comes **before** `<dependencies>` because a policy can induce a dep edge; the LLM must decide which policies apply before enumerating deps, so policy-induced deps land naturally in `<dependencies>` rather than being backfilled. Subcomponent arch docs omit this section — they introduce no new responsibilities to target.
- `<dependencies>` — the list of sibling components this one reaches for, by stable ID. Parseable separately because it feeds dependency-edge edits and cycle detection. Always generated *after* `<policies>` in the same LLM call.

The system architecture node has its own `<technical-specification>` section at the top-level tier, where project-wide concerns like language choice and runtime targets live. Subordinate tech specs inherit those constraints; child tech specs may narrow the parent's choices but not contradict them. The sysarch's `<policies>` section is where top-level (project-wide) policies live; component arch docs' `<policies>` sections hold component-local policies.

**Fragments are transcluded.** Each parseable section is a **fragment** with its own stable ID of the form `<owner_id>_<fragment_kind>` — e.g. `comp_a3f7k2m9_pubapi` is the public surface fragment owned by component `comp_a3f7k2m9`. Fragment kinds are a closed vocabulary (`techspec`, `pubapi`, `privapi`, `policies`, `deps`), fragment kinds are required to be single-token (no underscores inside a kind name), and the parser splits on the last underscore, so `<owner_id>` is stable and opaque and `<fragment_kind>` is always unambiguous.

When a dependent component needs to know what its upstream exposes, its regen prompt pulls the upstream's `pubapi` fragment by ID. The upstream's full arch doc never enters the prompt — only the fragment. This is the load-bearing scoping that keeps prompts bounded as the project grows, and it also makes fragment-level diffs the natural unit of propagation: a change confined to `<technical-specification>` does not invalidate dependents that only read the `pubapi` fragment.

**Disagreement detection is a fragment diff.** If the system architecture claimed a component would expose one API and the component arch ended up exposing a different one, the system architecture's copy of `comp_X_pubapi` and the component arch's copy diverge. That is the drift signal, surfaced naturally as a diff over two fragment instances with the same ID.

Inside `<public-surface>` and `<private-surface>`, code-shaped content lives in language-agnostic fenced code blocks. The parser doesn't inspect the code — it just pulls the tagged section whole. This means the generated code can be in any language and the fragment machinery doesn't have to care.

### A.1.6 Foundation components

Every level of the structural tree has **shared files at its root** — build config, package init, cross-cutting utilities, top-level entry points — that don't logically belong to any one child. Without a dedicated owner, those files are orphaned by the file manifest and by code generation: no impl node produces them, no plan node touches them, and the resulting project isn't buildable.

To fix this by construction, every structural decomposition pass is required to mint a **foundation component** as one of its children:

- **Sysarch** always includes a foundation component in its top-level component list. Its territory covers the project's root folder minus whatever the other top-level components claim.
- **Each component-architecture pass** that decomposes a component into subcomponents includes a foundation subcomponent, **unless the component being decomposed is itself a foundation component**.

**Foundations don't nest.** When a foundation component — top-level or sub — is itself decomposed by a component-architecture pass, that pass does **not** mint another foundation subcomponent inside it. Instead, the generation prompt is told to **divide the foundation's territory exhaustively**: every file the foundation owned must be claimed by one of the concrete subcomponents it mints, with no residual catch-all. The reason is that "foundation" means "catch-all at this level," so a sub-foundation inside a foundation would be the catch-all of the catch-all, which collapses to the original. Nesting the concept double-counts the role and leaves the user looking at a tree whose structure doesn't describe anything real.

Whether a component is a foundation is persisted as a first-class attribute on the node, set at mint time by the sysarch and component-architecture mint handlers based on the parsed foundation marker in the upstream arch doc. Downstream passes read it directly rather than re-parsing upstream content.

A foundation component is a normal `comp_*` node in every other respect — it has its own responsibilities, its own fragments, its own dependencies, and it can have subcomponents if it decomposes further (subject to the depth cap and the nesting carve-out above). It is not a special tier or a special kind; it is a conventional child that the generation prompts are required to always produce, with the one carve-out. Naming is free — the LLM defaults to "Foundation" but the user can rename, and a project that calls its root layer "Platform" or "Core" is equally valid.

The foundation rule guarantees three things: manifest coverage (every file at every level has an owner, because the foundation's territory is the catch-all remainder), code-generation buildability (the top-level foundation owns the build config and entry points so the first code-gen pass produces a compilable project), and a natural home for cross-cutting utilities (shared types used by multiple subcomponents land in the foundation without having to be artificially extracted as a standalone top-level component first).

### A.1.7 Subcomponent depth cap

The `comp_*` kind is tier-agnostic for ID purposes — promotion and demotion between top-level components and subcomponents must not change the ID, so both tiers share the prefix — but the structural tree is **hard-capped at two levels**. A `comp_*` whose parent is another `comp_*` cannot itself be the parent of any `comp_*`. In other words: component → subcomponent → impl is the full allowed structural chain; no sub-subcomponents, ever.

Rationale: three-level component trees are harder to review, harder to render, and add only marginal expressiveness beyond what "promote the middle layer to its own top-level component" already provides. Promotion is a single operation in the structural-edit UI, and it is the right answer whenever a subcomponent's decomposition would need its own children. Capping the tree saves the system from supporting promote/demote flows that reason about unbounded nesting.

The cap is enforced by the reducer on every structural event whose target tier is `comp` — `NodeCreated`, `NodeReparented`, `NodePromoted`, `NodeDemoted`. If the chosen parent is itself a `comp_*` whose own parent is a `comp_*`, the event is rejected before it is applied. The component-architecture regen prompt is also told about the cap explicitly, with the escape hatch framed as: "if decomposition would require three levels, stop and recommend promoting the middle layer to a top-level component."

Knock-on consequences:

- **Subresponsibilities are a leaf responsibility tier.** "Subresp → subcomp" is the full story; there are no sub-subresps. Policies generated at the component-architecture tier therefore have a well-defined universe of subresps to target.
- **Fan-in nodes never nest.** A fan-in (A.1.9) synthesizes across one component's direct subcomponents, which is now also the only structural possibility.
- **Policies have exactly two generation tiers**, matching the two tiers where responsibilities are minted. Top-level policies live in the sysarch's `<policies>` fragment; component-local policies live in each component's arch-doc `<policies>` fragment. No recursive policy-generation pass is needed.

### A.1.8 Unified domain and presentational DAG

There is no separate domain graph and presentational graph. Domain and presentational nodes share the same shape — feature → responsibility → component → subcomponent → impl — and the distinction is a `kind` tag on the node, not a different data model. Presentational nodes are strictly layered *after* domain nodes in the generation order: a presentational component can depend on a domain component's public surface, but a domain component cannot depend on a presentational one.

- **Dependency edges cross kinds.** A presentational component depending on a domain component via the latter's public surface is the normal "I import your API" edge and behaves the same regardless of the kind distinction.
- **Domain-parent edges mark primary views.** These are `presentational → domain`, 1:N, and indicate the domain component(s) this presentational component is a *primary view* into. The semantics differ from dependency: a primary view needs to reflect what was actually built at the domain side, not just the API contract, which is why domain-parent edges feed fan-in synthesis nodes (A.1.9) while dependency edges feed only public surfaces.
- **Sibling means "same parent / same level," not "same kind."** A presentational component can have domain components as dependency siblings in the context-assembly sense. A notifications UI component, for example, may have no domain parent (notifications isn't a primary view into a single domain concept) but depends on several domain components for the data it shows.
- **Admin surfaces, docs pages, and UI features are regular features.** They are not a third node kind. Each such surface is a presentational feature with its own domain-parent edges where they make sense and plain dependency edges everywhere else.

Presentational generation prompts read two kinds of context from the domain side: the domain component's spec (the top-down intent) and the domain component's fan-in synthesis (the bottom-up "what exists"). If those two disagree, that is a meaningful signal that the domain side has drifted from its own contract, and the presentational regen is the natural place for it to surface.

### A.1.9 Domain fan-in synthesis nodes

Domain-parent edges carry far more context than plain dependency edges. A dependent that just imports an API only needs the public surface; a presentational node that is a primary view *into* a domain component needs to faithfully reflect what was actually built underneath, not just the contract.

To carry that load without inflating presentational regen prompts, **every domain component with subcomponents gets a fan-in synthesis node** sitting at the bottom of its subtree, regardless of whether a presentational counterpart currently exists. Always-minting is a deliberate simplification: adding a domain-parent edge later never has to retroactively materialize a fan-in, and the minting rule is purely a function of the domain subtree shape. The cost is a few extra regens for fan-ins nobody is reading yet, which is acceptable.

Domain components without subcomponents don't need a fan-in — their own implementation node already is the synthesis, and a presentational counterpart reads it directly.

```
domain feature
  → domain responsibility
    → domain component (spec / contract)
      → domain subcomponents
        → subcomponent implementations
          → fan-in synthesis           ← bottom of the domain accordion
            → presentational counterpart (cross-tree, via domain_parent edge)
```

Properties of fan-in nodes:

- **Strictly downstream of subcomponent implementations.** They synthesize "given these subcomponent implementations, here is what this component actually exposes and does at the component level." They never read their own domain component's spec directly — that would be circular.
- **Feed only presentational counterparts.** Current or future, via domain-parent edges. Fan-ins are never read by their own domain component, so domain-side regeneration stays single-pass top-down with no upward propagation.
- **Real projection nodes with their own diffs and their own staleness.** When a subcomponent implementation changes, the fan-in regenerates, and *its* diff is what reaches the presentational side. A presentational node reading a fan-in never sees N subcomponent diffs directly — its input set is bounded no matter how big the domain subtree grows.
- **One fan-in per domain component, not one per level.** The synthesis collects the entire subtree below the component in a single rollup. Subcomponents don't get their own fan-ins.
- **Not reviewed directly.** Fan-ins are mechanical synthesis; real edits land at the subcomponent implementations below them, and "does this reflect what was built" is actually checked at the presentational counterpart. Reviewing the fan-in itself would be triple-counting the same diff. Fan-ins are excluded from review scoping.
- **Always-present even without a presentational counterpart.** Minted unconditionally for any domain component with subcomponents. Adding a domain-parent edge later is then a pure edit, not a mint-on-the-fly.

A presentational counterpart reads two inputs from the domain subtree: the **spec** from the domain component (top-down intent) and the **fan-in** (bottom-up "what exists"). If those two disagree, that is a meaningful signal that the domain side has drifted from its own contract, and the presentational regen is the place where it surfaces.

### A.1.10 Policies

Some content isn't a capability, it's a constraint: "every LLM call records telemetry," "every DB write goes through the reducer," "every route checks the session." These aren't things *one* component does — they're things *every* component does, and they need to be both **stated** (so the LLM writing an implementation knows about them) and **reviewable** (so a human can confirm a cross-cutting invariant still holds).

The capability a policy requires is still modeled as a normal component — `TelemetryService`, the reducer, the session check — reached via ordinary dependency edges. What's new is the *policy itself*: the statement that the capability must actually be used at every trigger site.

**Shape of a policy.** A `policy_*` node carries three fields:

- **`trigger`** — a short semantic phrase identifying the site type where the policy applies: "any LLM call," "any DB write," "any presentational route handler." The policy-application pass reads this and decides whether the trigger plausibly occurs in a given component, based on that component's techspec, public surface, and subresponsibilities. It's semantic, not a structural identifier, so the trigger vocabulary doesn't need a central registry — a new kind of cross-cutting concern is just a new policy with new trigger wording.
- **`required`** — the ID of the responsibility (`resp_*`) that must be fulfilled at every trigger site. Policies reference responsibilities, not components directly, because the resp → comp 1:1 mapping gives the application pass the concrete component to call while keeping the policy stable across component refactors: if `TelemetryService` gets merged or split, the `resp_telemetry` it fulfills moves with it and the policy wording doesn't change.
- **`rationale`** — prose explaining why the policy exists. Shown in review and included in regen prompts so the LLM understands intent. Carries real weight in the application decision — "record latency for anything a user waits on" tells the LLM what kind of trigger sites to look for.

Policies live in the `<policies>` fragment of an arch doc. On approval, the reducer parses the fragment and projects each entry into a `policy_*` node, the same way the `<dependencies>` fragment projects into dependency edges. The fragment is the authoring surface; the node is the identity that `policy_application` edges reference.

**Two generation tiers, matching the two responsibility tiers.**

1. **Top-level policies** — generated as part of the sysarch joint-reasoning pass, alongside components, API intent, and dep edges. Live in the sysarch's `<policies>` fragment. Trigger phrases can match against the full component set. The `required` field references top-level `resp_*` nodes minted by the requirements bootstrap.
2. **Component-local policies** — generated as part of each component's arch-doc pass, alongside subcomponents and that component's deps. Live in the component arch doc's `<policies>` fragment. Trigger phrases match only against components in the minting component's subtree. The `required` field references either top-level responsibilities or this component's own subresponsibilities, whichever the obligation actually needs.

Subcomponent arch docs have no `<policies>` section; subcomponents are leaves, so there are no new responsibilities to target with new policies and no subtree to scope new triggers against.

**Application happens at component-architecture time, not at sysarch approval.** "Does this policy apply to this component?" is an LLM decision that needs the candidate component's full techspec, public surface, and subresponsibilities available as input. At sysarch approval time, the sysarch's per-component summary is deliberately high-level — role plus API intent only — because the whole point of the sysarch/component-arch split is that sysarch entries stay stable as subcomponents iterate. At that level of detail, the application pass cannot confidently answer "does this component have trigger X."

So the application pass runs at component-architecture generation time:

1. **Sysarch generation** produces `<policies>` in its output as normal. On approval, `policy_*` nodes are projected from the fragment. **No `policy_application` edges are emitted yet for top-level policies.** Policy nodes exist, but they have no application edges.
2. **Sysarch emits speculative policy-induced dep edges** in its `<dependencies>` section, based on role-level inference against the per-component summaries it does have ("this component's role involves generating content, so it probably needs `TelemetryService`"). Best-effort. A missed dep at this stage can be patched at component-architecture time.
3. **Component architecture generation** receives the full list of top-level `policy_*` nodes as candidates in its regen prompt. The LLM reads the component's techspec, subresponsibilities, and public surface, and decides for this specific component which policies actually apply. Component-local policies minted in the same pass go through the same application step, scoped to the component's own subtree.
4. **`policy_application` edges are emitted on component-architecture approval**, one per (policy, this-component) pair the LLM marked as applicable. The component arch's own `<dependencies>` list also gets a chance to add any policy-induced dep that sysarch's first pass missed.

**Policy-induced dependency edges** exist because a policy that says "at any trigger site, fulfill responsibility X" implicitly requires every applicable component to depend on whichever component owns X. Those dep edges have to exist or the generated code cannot reach the required capability. This is why `<policies>` comes *before* `<dependencies>` in the arch-doc section order: the LLM is expected to reason about policies first and then emit a dependency list that already reflects policy-induced edges.

**Application edges are editable but not formally reviewed.** The instruction vocabulary includes operations to add or remove a policy application for cases where the LLM's decision is wrong (false positive or false negative). User overrides are normal structural edits. Edges aren't reviewed separately because the *policies themselves* are reviewable — they're part of the arch doc's `<policies>` fragment — and if a policy turns out to be too broad or too narrow, the fix is to edit the policy wording or its trigger, not the edges one by one.

### A.1.11 Component ownership and repository territory

Every top-level component and every subcomponent has an **owner** — the team member who is the default reviewer for everything in that subtree: architecture docs, subrequirements, change plans, implementation nodes, plan nodes, and the code that ships from its leaves. Ownership is not a separate binding but an instance of the scoped-role system (A.14.2): the user holds the `owner` role with a scope pinned to the component's ID, and the permission atoms the role grants apply only within that component's subtree.

**Fan-out is the natural assignment point.** When a decomposition pass produces new components (sysarch minting top-level comps, or a component architecture doc minting subcomponents), the user approving that decomposition is prompted to assign owners for the new children alongside approving the decomposition itself. Ownership is part of the approval, not a separate step. A component may transfer ownership later — the `owner.transfer` permission atom controls who can initiate the move, and the new owner's scoped-role binding replaces the old one.

Ownership flows down by scope: an owner at the `comp_abc` scope implicitly owns every subcomponent, subresp, policy, impl, plan, and change-plan artifact in `comp_abc`'s subtree. A sub-owner at `comp_abc.comp_def` can be assigned alongside the parent owner, in which case permission checks consult both and use the most-specific match — useful for "I own this component but delegate the auth subcomponent to Bob."

Responsibilities, features, and policies are project-level artifacts without single natural owners. They are reviewed by whoever owns the component(s) that decompose them, and permission checks against those artifacts fall through to project-scoped roles.

**Repository and folder territory.** For the code-generation side of the system, each leaf maps to a `{repository, folder}` pair called its **territory**. For the MVP, all leaves within a project target a single repository (monorepo assumption), but the data model supports multi-repo via the `{repository, folder}` mapping so multi-repo projects are a post-MVP extension without a data-model change.

Within a repository, each impl node corresponds to a folder — the leaf's territory — and is the only node allowed to write files in that folder. This gives a direct, deterministic mapping between the structured model and the codebase. The mapping is enforced in code-generation prompts and in AI sandboxing (A.18), which prevents a leaf's coding assistant from reading or writing files outside its territory.

The top-level foundation component's territory is the project's root folder minus everything the other top-level components claim. Each nested level's foundation subcomponent likewise owns its parent's root folder minus its siblings. This is how the file manifest achieves full coverage: every file at every level has an owning impl node because the foundation rule defines the catch-all remainder explicitly at every nesting level. See A.1.6.

The **manifest** node (one per project, singleton) is the authoritative mapping from folder path to owning leaf. The manifest is minted and regenerated by the code-generation passes, not authored directly, and lives in the event log like every other node. When a structural operation reshapes the component tree (split, merge, reparent, promote, demote), the manifest is regenerated as part of the same flow so that territory stays aligned with the tree. An orphaned folder — one not claimed by any leaf — is a manifest-level error surfaced in the admin tools (A.21.4).

### A.1.12 Project vocabulary

Every project has jargon. "Boulder" in one project is a container with internal structure; "boulder" in another is a blocker issue that can't be moved past. "Tranche" in a finance product is a debt-security slice; in an invoicing pipeline it might be a time-bounded batch of work. Generic LLM priors fight project-specific meanings at every regeneration where the project's definition isn't fresh in the prompt context, and when the priors fight, the LLM quietly substitutes its defaults and produces silent drift toward generic meanings. Per-node regeneration with bounded context windows is exactly the environment where definitions are most easily forgotten, and the cost of forgetting is architectural decay.

A dedicated vocabulary layer makes project-specific term definitions structured, addressable, and always-included in regeneration context. Vocab entries are **entities, not content** — they have names, content, edges to other entities (cross-references between terms, planned as a post-MVP extension), their own edit/review lifecycles, and their own place in the project's audit trail. Modeling them as a node tier rather than as a fragment on another node is what gives them all of that: fragments are sections of a larger document, reviewed as part of their owner, and they can't participate in edges. Vocab entries can, and need to.

**Scope via `parent_id`.** A vocab node with `parent_id = null` is a project-level term — every regeneration at every tier sees it. A vocab node with `parent_id` set to a `feat_*` id is a feature-local term — only regenerations reachable from that feature via decomposition see it. The reducer enforces this directly: a `vocab_*` node's parent, if set, must be a `feat_*`. Parenting vocab under a component, responsibility, or any other tier is rejected at event-apply time, because scoping vocab below the feature layer would leak project-specific terms into arbitrary internal decomposition and defeat the purpose of having a coherent project-wide vocabulary.

**Promotion between scopes is reparent.** A feature-local term that turns out to be useful project-wide gets promoted with a `NodeReparented(vocab_id, new_parent_id=null)` instruction. The term keeps its id, its content, its edit history, and (once cross-reference edges land) its `vocab_reference` edges. This is the same reparent primitive used for component promotion and demotion; vocab gets it for free.

**Content shape is structured XML.** Each vocab entry's `Node.content` holds a `<vocab-entry>` block with three children in fixed order: `<definition>` (required, non-empty prose describing the term), `<disambiguation>` (optional — a "not to be confused with" note that directly counteracts LLM priors, and is strongly encouraged for any term whose project-specific meaning diverges from a common one), and `<see-also>` (optional — a list of `<ref name="..."/>` or `<ref to="vocab_..."/>` elements cross-referencing other terms). The grammar is parseable, validated at authoring time, and fits the same family as component and subcomponent arch docs. Storing XML from day one means the `vocab_reference` edge type — a post-MVP addition that would emit `EdgeCreated(edge_type="vocab_reference", source=this_vocab_id, target=ref_id)` for each resolved reference — becomes a one-function follow-up rather than a retrofitted parser over prose.

**Render-time transformation for prompts.** The storage format is XML; the prompt format is prose. At context-assembly time, a formatter walks each vocab entry's stored XML and renders it as human-readable text: "Definition: ... / Disambiguation: ... / See also: term1, term2." The LLM sees readable definitions rather than raw tags. This decouples storage from prompt-friendliness — extending the XML grammar (for categories, deprecation flags, alternate names, anything else we decide vocab entries should carry) requires only updating the formatter to include new fields in the prose rendering, with no stored-content rewrite or migration. Prompt tokens are too expensive to spend on XML syntax the LLM doesn't need.

**Minting.** Vocabulary is projected from the expansion bootstrap. The expansion output gains an optional `<vocabulary>` section sibling to `<features>`, containing `<term>` elements with `name`, `scope`, and (when scope is feature) `feature-alias` attributes. Each `<term>` contains a single `<vocab-entry>` inner block matching the grammar above. On expansion approval, `feat_*` and `vocab_*` nodes are minted in the same transaction; the alias-to-id map built during feature minting resolves `feature-alias` attributes on vocab entries to their target `parent_id` values. Feature-request and refactor flows that introduce new jargon also project new vocab entries via the same mechanism.

**Context assembly.** Every regeneration prompt at every tier sees the project vocabulary. Project-level entries are always included; feature-local entries are included for every feature reachable from the regen target via the decomposition walk (features the target's subtree serves, computed from the `feat → resp → comp → resp → comp` chain). The vocabulary partition has its own context-budget allocation separate from parent architecture, sibling pubapis, or change-plan context — vocabulary doesn't compete with architectural content for budget because the cost of forgetting a term once is higher than the cost of including it every time.

**Direct user creation outside a flow.** The instruction vocabulary includes a `CreateVocabEntry(name, content, parent_id)` operation so users can add terms without running a flow. A reviewer who notices a term that needs definition clicks "add term" in the vocabulary UI, fills in the name and the `<vocab-entry>` body (or lets the LLM generate an initial draft from a one-line prompt), and the instruction flows through the pending-change queue like every other structural edit. Renaming, reparenting, and deleting a vocab entry all reuse existing `NodeRenamed` / `NodeReparented` / `NodeDeleted` instructions.

**Exclusion from structural views.** Vocabulary is not shown in the decomposition graph, the component tree, or any other structural visualization. Vocab entries are not part of the project's architectural shape — they're metadata about the terms the architecture uses. The UI surfaces vocabulary through a dedicated "Vocabulary" tab on the project dashboard, a per-feature vocab panel on feature detail views, and inline definition tooltips or hovers wherever a known term appears in a rendered artifact. This keeps the structural view uncluttered and gives vocabulary its own first-class home without fighting for pixel space with the core decomposition UI.

**Out of scope for the MVP:** LLM-discovered vocabulary (where the LLM notices it's using a term in a specific way and surfaces it as a candidate definition for review), `vocab_reference` edges as first-class graph entities (they will exist eventually, but initial implementation stores cross-references as `<see-also>` entries in stored XML without emitting edges), proliferation guardrails for projects that accumulate hundreds of terms, and automatic linking of vocabulary terms in rendered artifact prose (a parser that scans prose for known term names and linkifies them). All straightforward follow-ups; none are load-bearing for the initial vocabulary layer.

## A.2 Flows

The system supports four flow types. Only one flow run (or sub-run) may be active per project at a time — see A.7.

### A.2.1 Scaffolding flow

The default cold-start flow. Takes a raw input document and walks the full structured-model generation order (A.3.1) from input expansion down to code, minting every node from scratch.

- **Input expansion** — the `expansion_*` bootstrap produces a prose decomposition of the raw input into features. On approval, `feat_*` nodes are projected.
- **Requirements** — the `reqs_*` bootstrap takes the approved features and produces top-level responsibilities. On approval, `resp_*` nodes and `feat_* → resp_*` decomposition edges are projected.
- **System architecture** — the `sysarch_*` bootstrap produces the top-level component graph: components, API intent, top-level policies, dep edges, domain-parent edges, and a system-level techspec. On approval, `comp_*` nodes (including the foundation component), top-level `policy_*` nodes, dep/domain-parent edges, and one `subreqs_*` bootstrap per top-level component are projected.
- **Subrequirements** — per top-level component, the `subreqs_*` bootstrap decomposes that component's top-level responsibilities into subresponsibilities. On approval, the `resp_*` subresp children and `top_level_resp → subresp` decomposition edges are projected.
- **Component architectures** — generated in dependency topological order after each component's subreqs is approved. Each produces the component's fragments (techspec, pubapi, privapi, policies, deps), plus subcomponents (with the foundation subcomponent rule), sub-dependencies, and `policy_application` edges from top-level and component-local policies.
- **Subcomponent architectures** — generated per subcomponent after the parent component's arch doc is approved. Four fragment sections (techspec, pubapi, privapi, deps) — no policies section because subcomponents are leaves.
- **Implementation nodes** — one per subcomponent and one per un-fanned-out component. Carries the detailed design and build content the arch doc deliberately abstracts away. Maps to a folder on disk via the manifest.
- **Plan nodes** — per impl, translating impl-level intent into a concrete change list.
- **Code** — generated as a final leaf pass, plan by plan, in dependency topological order, bounded by each leaf's territory.

Each step produces one or more draft artifacts for human review. Each tier's draft runs through AI self-review first, then lands in the review queue for the assigned owner. Approval at any tier unblocks the immediately-downstream work via the scheduler (A.3.2) — no tier enqueues its successor directly.

### A.2.2 Feature request flow

Input is a prose feature description ("add billing," "let users share documents with external viewers"). The flow does **not** skip straight to minting a new feature — it first runs a **phase-zero expansion** that takes the request and decomposes it into one or more concrete features, because a user request is often really several features that need to be split before the rest of the pipeline can route them correctly.

Phase zero produces a small expansion-doc-style artifact: a structured list of features the request implies, each with a short name and intent. The artifact is reviewable with prose feedback like any other bootstrap output. On approval, the features enter the existing feature → responsibility → component → subcomponent chain as fresh mints, incremental to the already-projected state.

**Change plans at every level.** Alongside the node regen at each tier the request touches, the flow produces a `changeplan_*` node describing what this request means at that tier:

- A system-level change plan: "this request adds a new billing feature, which will spawn two new top-level responsibilities in reqs and affect the sysarch pass by introducing one new top-level component and adding policy applications to existing ones."
- Per-component change plans for components the request touches: "this component needs a new subresponsibility for invoice rendering; its subcomponents will gain a PDFRenderer subcomponent; its deps will add comp_billing."
- Per-subcomponent change plans for subs that inherit the change: "this subcomponent's pubapi needs to expose a new method for invoice_render; private helpers are unchanged."

Each change plan goes through the full draft → AI-review → human-review → approve lifecycle. Change plans are **not structural DAG nodes** — nothing depends on them via dependency edges, and they don't project structured children on approval. They are per-flow-run review surfaces that document intent. They persist in the event log as provenance (A.4.3) so that "why did this regen happen, and what was the thinking at each level?" is answerable long after the flow run completes.

The change plan at each tier is consumed as prompt context by the regen at that tier. The upstream change plan is in the downstream's context, so by the time the subcomponent tier runs, the LLM has seen how the whole chain interprets the request.

### A.2.3 Refactor flow

Same shape as the feature request flow, different input semantics. The input is a refactoring objective ("extract the caching layer out of the billing service into its own top-level component," "rename Policy to Rule throughout") rather than a feature description. The same phase-zero expansion runs to produce a list of structural operations the refactor implies, and the same per-tier change plans drive per-tier regens.

Structural operations — reparent, promote, demote, merge, split, delete — are produced as instructions in the change plan and applied at the end of the flow run, because they are destructive and need explicit approval. Non-structural operations (rename, API changes, policy edits) apply immediately as they land through the regen pipeline.

Refactor and feature request share enough machinery that they could collapse to a single flow with a "mode" flag. Keeping them separate in the vocabulary is a UX choice: users have strong mental models about which they're doing, and the lobby (A.6) shows them as distinct flow kinds so queued work is easier to reason about.

### A.2.4 Bug-fix propagation flow

Input is an existing code change — a PR, a commit, a diff — that has already modified the codebase outside Catapult, or that was made manually in parallel with Catapult. The job is to propagate the implications of that code change **upward** through the structured model so that the design graph catches up to reality, and then **sideways** through sibling subtrees that the changes affect.

This flow is genuinely different from every other flow described above. The others walk the generation order *top-down* from some upstream change; this one walks *bottom-up* from many leaves at once.

1. **Leaf identification.** The input diff is mapped back to `impl_*` nodes via the territory manifest (A.1.11). Every file in the diff belongs to exactly one leaf; the full set of affected leaves is the starting set for the flow. A single bug-fix commit may touch multiple leaves in unrelated subtrees, and the flow handles the full set in one run rather than forcing the user to run one flow per leaf.
2. **Leaf diagnosis.** At each affected leaf, a diagnosis node analyzes what the code change implies about the gap between the documented implementation and the code that actually shipped. Diagnosis is prose: "this change fixed a race condition in the retry scheduler by adding a mutex; the impl doc didn't mention thread-safety requirements, and the plan assumed single-threaded retry execution." The diagnosis is a reviewable change-plan-like artifact at the leaf layer.
3. **Upward pass with merge-at-parent.** Parent components wait until **all** affected descendants have produced their diagnoses before running their own diagnosis + change plan. Merging at the parent means the parent sees a single coherent picture of everything the change means for it, rather than running N separate regens for N child diagnoses. The change plan at the parent proposes updates to the component's fragments (techspec, pubapi, privapi, policies, deps) and to its subcomponent decomposition if the diagnosis implies structural drift.
4. **Upward pass continues through the sysarch and optionally through the reqs bootstraps.** If the change implies something new about the project's top-level responsibilities or the system-architecture layout, the phase-0 expansion artifact and the reqs or sysarch node are updated. If not, the upward pass terminates at whatever level stops producing meaningful diagnoses.
5. **Downward sibling pass.** At every structural-layout node touched during the upward pass (each component, plus sysarch if it was touched), the change plan identifies *other* children that are implicated by the merged changes — not just the ones on the original upward path. A change to the telemetry policy discovered via a leaf fix may require updating every component that has the telemetry trigger. The downward pass is a per-parent fan-out over these identified siblings, each producing their own change plan + regen, recursively until there are no further implications.
6. **No code is generated by this flow.** The input is already code; the output is design updates that bring the structured model into alignment with what exists. A follow-up feature-request or refactor flow can be scheduled if the diagnosis reveals work that still needs to happen, and the resulting code changes ship through the normal code-generation path.

This flow is how Catapult stays coherent when the codebase moves outside its control. Hotfixes, external contributions, automated dependency bumps, manual edits made directly in the repository — any case where the code has moved and the design memory needs to catch up — route through this flow. If the change was made through the normal Catapult flow, the bug-fix flow is not needed because the design updates already happened upstream before the code did.



## A.3 Phases and generation order

### A.3.1 Cold-start generation order

The cold-start pipeline runs through a fixed topological order. Each tier has its own prose, its own approvals, its own generation prompt, and its own position in the chain. The sequence is load-bearing because downstream tiers reference upstream IDs that must already be minted and stable at the moment the downstream regen runs.

1. **Input document** — the raw prose the user brings in. The only node the user authors directly.
2. **Feature expansion (`expansion_*`)** — prose decomposition of the input into features. Approved as a standalone document before any feature nodes exist. On approval, `feat_*` nodes are projected.
3. **Requirements (`reqs_*`)** — singleton. Decomposes the approved feature set into top-level responsibilities. On approval, top-level `resp_*` nodes plus `feat_* → resp_*` decomposition edges are projected.
4. **System architecture (`sysarch_*`)** — singleton. Takes the top-level responsibilities and produces the component graph: components (including the foundation), API intent, top-level policies, dep edges (including policy-induced edges), domain-parent edges, and a system-level techspec. Approval mints `comp_*` nodes, top-level `policy_*` nodes, dep/domain-parent edges, and one `subreqs_*` bootstrap per top-level component. Top-level policy application edges are **not** yet emitted — they're resolved against each component at component-architecture time.
5. **Subrequirements (`subreqs_*`)** — per top-level component, minted at sysarch approval. Decomposes the component's top-level responsibilities into subresponsibilities. On approval, subresp `resp_*` children and `top_level_resp → subresp` decomposition edges are projected. Component-architecture generation for a component cannot run until its subreqs is approved.
6. **Component architecture docs** — generated in dependency topological order after the owning component's subreqs is approved. Each consumes the sysarch's entry for it (role + API intent), the public surfaces of its dependencies, and the pre-minted subresponsibilities from step 5. Each also produces component-local policies targeting those subresps, and on approval is where top-level and component-local policies are resolved against this component: the LLM reads the now-detailed techspec and subresps and emits `policy_application` edges for the policies that actually apply.
7. **Subcomponent architecture docs** — generated in dependency topological order within each component. Leaf tier — no further decomposition, no `<policies>` section. Four fragments only: techspec, pubapi, privapi, deps.
8. **Domain fan-in synthesis nodes (`fanin_*`)** — minted as part of sysarch (and regenerated as subcomponents iterate). Always present for every domain component with subcomponents, regardless of whether a presentational counterpart currently exists.
9. **Implementation nodes (`impl_*`)** — one per subcomponent and one per un-fanned-out component. Carries the detailed design and build content, distinct from the parent's abstract techspec.
10. **Plan nodes (`plan_*`)** — per-impl, translating an impl-level intent into a concrete code-change list.
11. **Code** — generated as a final leaf pass, plan by plan, in dependency topological order, limited to the leaf's territory.

The two-tier decomposition split (reqs/sysarch at the top, subreqs/comparch per component) is what resolves the chicken-and-egg of "component A's regen needs component B's public surface but B hasn't been generated yet." By committing to top-level responsibilities, then API intent, then each component's subresponsibilities up front, dependent components have stable IDs and bounded contracts to reference even before the downstream components have been generated in detail. Component architectures then flesh the intent into full public-surface detail, and the sysarch's API entry for each component is a transcluded fragment of the component arch (A.1.5) so drift is detectable as a fragment diff.

### A.3.2 State-driven scheduling

Generation is **not** chained by emission. A handler that produces an event does not also enqueue the next generation job. Instead, a dedicated **scheduler** watches application state and decides what to run next, and the scheduler is the *only* path into the job queue. Mint handlers and regen handlers commit their events and exit; whatever runs next is the scheduler's decision, computed from the projected state.

The scheduler's logic is a set of queries over the projection, each expressed as "for every node in state X matching condition Y, and for which no job is currently queued or running that would produce Z, enqueue job Z." Examples:

- "For every top-level `comp_*` whose subreqs is approved and whose own content is empty and which has no pending `generate_comparch` job, enqueue `generate_comparch`."
- "For every subcomponent `comp_*` whose parent's comparch content is non-empty and whose own content is empty and which has no pending `generate_subcomparch` job, enqueue `generate_subcomparch`."
- "For every `impl_*` whose parent arch doc is approved and whose own content is empty, enqueue `generate_impl`."
- "For every subtree with pending staleness markers and no active regen, enqueue a regen for the marked nodes in dependency order."

The scheduler is the only place these rules are stated. Adding a new generation tier or a new flow kind means adding new scheduler queries, not hunting through every existing handler to teach it about the new downstream.

**Trigger mechanism.** The scheduler re-runs its queries on two paths. The **fast path** is a `Phoenix.PubSub` subscription: after every successful reducer commit, a notification is broadcast on the project's topic and the scheduler picks it up and re-runs its queries within milliseconds. The **slow path** is a sweeper that runs on a floor interval (configurable, default 30-60 seconds) and executes the same queries unconditionally, catching anything the fast path missed due to subscriber restart, signal loss, or race conditions. The fast path is the latency ceiling; the sweeper is the consistency floor.

**Concurrency.** The scheduler does not hold its own locks. Idempotency is enforced at the job-queue layer: every job the scheduler enqueues carries a uniqueness constraint on `(worker, args, queue, states)`, and Oban's insert path rejects duplicates via a Postgres unique index (B.4). Two simultaneous commit signals — or two BEAM nodes running the scheduler in a clustered deployment — produce the same query results and attempt the same inserts, and the duplicates are rejected at the database layer rather than coordinated by a scheduler-level lock. The scheduler itself is effectively stateless: a pure function that reads projection state and writes job intentions.

**Why state-driven, not event-driven.** Handlers emitting the "next job" was the old pattern and had two problems: new flow types required teaching every upstream handler about the new downstream, and crash-recovery was fragile (a handler that committed its events but failed to emit the next-job message left a hole in the chain). State-driven scheduling makes both of these go away: new flows just add scheduler queries, and crash recovery reduces to "the scheduler wakes up and re-queries current state," which is the same code path the fast path runs anyway.

### A.3.3 Approval gates only destructive operations

A change to a node propagates to its neighbors immediately, with one carve-out: **operations that would destroy or reshape content downstream are gated on explicit user approval of the originating node.** Everything else propagates without blocking the user.

The reason for the carve-out is asymmetry. Most edits — public-surface changes, implementation tweaks, dependency-edge edits, renames, reparenting, promotion, demotion — are reversible. Content carries forward through regen via lineage references, prior versions live in the event log, and a regen the user doesn't like can be rolled back by walking the log. The worst case of a "wrong" non-destructive cascade is some redundant LLM work and the inconvenience of reviewing the result. No user prose is lost.

Destructive operations are different. They include:

- **Delete** — cascading to children would lose all their content with no recovery short of replaying the event log to a prior offset.
- **Merge** — reconciling overlapping content forces the LLM to drop or summarize material, and the dropped pieces can be exactly the prose the user has been iterating on.
- **Split** — distributing one source across multiple destinations has the same loss profile.

These three gate. Everything else runs. The gate exists specifically to prevent unrecoverable content loss, not to make the user babysit every cascade. Without this narrowing the original "gate everything" rule would block even obviously-safe edits and train the user to click through without reading, which defeats the point.

**Corollary: initial mint is destructive at the child level.** When a bootstrap node is approved and projects its children (features from expansion, responsibilities from reqs, components from sysarch, subresponsibilities from subreqs), the mint commits to a particular shape, and if the user wants a different shape, the mint is the moment to catch it. After the mint, edits to the minted children propagate normally.

**Second corollary: the bootstrap nodes (`expansion_*`, `reqs_*`, `sysarch_*`, each `subreqs_*`) become read-only after initial approval.** Ongoing work at each of those layers happens as add / delete / edit on the individual minted children (features, top-level responsibilities, components, subresponsibilities), not by re-editing the bootstrap prose. There is no re-mint, only incremental edits at the child layer. The bootstrap node itself is kept in the event log as a historical reference but isn't a live editing surface.

### A.3.4 Fan-out pauses for review regardless of auto-approval

Fan-out operations — the steps that create new components or new subcomponents from a decomposition pass — always pause for human review, regardless of auto-approval configuration. Structural changes to the tree are too consequential to auto-approve; the reviewer needs to see what was minted, whether it's the right decomposition, and assign ownership to the new children.

This is a hard override on the auto-approval system. Projects configured for full auto-approval will still stop at fan-out boundaries. The carve-out is explicit because the intuition "auto-approve everything" and the intuition "but obviously I should see structural changes" have to be made to coexist without the user having to remember the distinction every time.

### A.3.5 Context assembly strategy

Context assembly uses a **strategy pattern** — different tiers and node types use different methods for gathering context. The context budget is **partitioned by category**, not applied as a single linear queue. Each strategy defines its own budget partitions based on what that node type needs:

- **Architecture nodes (system, component, subcomponent)** — budget weighted toward structural context: parent architecture (always in full), sibling summaries, the expanded input. Smaller allocation for semantic retrieval of distant ancestors.
- **Plan and impl nodes** — budget weighted toward the parent plan (always in full) plus current code state. Smaller allocation for ancestor architectures.
- **Fan-out / decomposition nodes** — budget weighted toward summary-level understanding of all children. Parent architecture in full. Minimal distant-ancestor context.
- **Change plans** — budget split between the user's request (always in full), the current state of the tier being planned for, and the upstream change plan (if any).
- **Project vocabulary** — a partition every regen prompt at every tier carries, separate from the partitions above. Project-level vocab entries are included in full (small, universal); feature-local vocab is included for every feature reachable from the regen target via decomposition walk. Vocabulary is rendered from its stored XML form into prompt-friendly prose at render time so the LLM sees readable definitions rather than raw tags. The partition's budget is configurable but defaults generously because the cost of forgetting a term once is higher than the cost of including it every time. See A.1.12 for the vocabulary layer itself.

Within each partition, the budget-based approach applies: include full documents nearest-first until the partition's budget is exhausted, then retrieve remaining context via semantic similarity from the vector index. The expanded input document and direct parent outputs are always included in full, drawn from the appropriate partition.

No node ever sees the full text of its dependencies — only their public-surface fragments and their diffs. No node ever sees the full implementation of its parent's other children — only what changed. This scoping is what keeps prompts bounded as the project grows.

**Future: intelligent context selection.** Documents are intended to store the complete design decision history of the project — they should never be compacted or summarized destructively. For very large or long-lived projects where documents exceed context budgets even with partitioning, a future version will need a context-building service that goes beyond vector search to select the most relevant portions of a document for a given prompt (structural analysis, recency weighting, decision-chain tracing). This is not needed for MVP but the context-assembly interface is designed to anticipate it.



## A.4 Projection sources, bootstrap nodes, and change plans

### A.4.1 Projection sources are the unifying abstraction

Throughout the model, several different constructs share one underlying pattern: **prose authoring surface → parse-and-mint on approval → structured DAG children**. These authoring surfaces are called **projection sources**. Bootstrap nodes, fragments, and change plans are all instances of the pattern, differing only in scope and lifecycle.

- **Bootstrap nodes** (`expansion_*`, `reqs_*`, `sysarch_*`, `subreqs_*`, `manifest_*`) are whole-document projection sources. The LLM writes the entire document, the user reviews it as a unit, and approval projects the content into structured children: `feat_*` nodes from an expansion, `resp_*` nodes plus `decomposition` edges from a reqs node, `comp_*` nodes plus techspec/pubapi fragments plus `policy_*` nodes plus dep edges plus domain-parent edges from a sysarch, subresp `resp_*` nodes plus their own `decomposition` edges from a subreqs, manifest path entries from the manifest.
- **Fragments** (`techspec`, `pubapi`, `privapi`, `policies`, `deps`) are section-of-document projection sources. They live inside component and subcomponent arch docs as tagged sections of those docs' content. Individual fragments don't have their own drafts — the arch doc is approved as a unit — but on approval, each fragment's content is projected separately: the `<policies>` fragment mints `policy_*` nodes, the `<dependencies>` fragment mints dependency edges, and so on. The arch doc is the approval unit; fragments are the projection units inside it.
- **Change plans** (`changeplan_*`) are per-flow-run review artifacts. They have the same draft → AI-review → human-review → approve lifecycle as bootstrap nodes but they **do not project structured children on approval** — instead, approval of a change plan at a tier unblocks the regen at that same tier by providing it as prompt context. Change plans are the review surface where the user agrees to *what* a flow will do at each level before the regen commits; the regen is the mechanism that actually does it.

The relationship — authoring surface → parse-and-project on approval — is the same across all three. What differs is scope and lifecycle:

| | Bootstrap nodes | Fragments | Change plans |
|---|---|---|---|
| Approval granularity | Whole document | Approved as part of the owning arch doc | Whole document |
| Storage | `Node.content` (one row per source) | `Fragment.content` (one row per kind per owner) | `Node.content` on the changeplan node |
| Lifecycle | Write-once; read-only after initial approval | Iterable; re-projected on every arch-doc regen | Write-once per flow run; read-only after approval |
| Persists in | Event log + projection | Event log + projection | Event log only; projection shows them in flow-run history, not in the live DAG |
| Projects structured children? | Yes | Yes | No |
| Addressable by other nodes? | No (bootstrap content is not transcluded) | Yes (fragment IDs are pulled by ID into dependent prompts) | No (no one references a change plan by ID) |

The storage and lifecycle asymmetry is load-bearing: bootstrap nodes don't need transclusion (nothing pulls a section of a reqs doc into another node's regen prompt), arch docs do (a component's `pubapi` fragment is pulled by every dependent's regen prompt), and change plans exist for audit and in-flow review but are not referenced by any permanent structural edge. Forcing either shape onto the others would lose information.

**The mint-handler code shape is identical** across bootstrap nodes and fragments: load inputs, parse the approved content, emit `NodeCreated` / `EdgeCreated` / `FragmentUpdated` events for the derived children, commit in one transaction. Change plans skip the "emit derived children" step — their mint handler records the approval event and the scheduler's queries pick up the downstream regen from there.

### A.4.2 Bootstrap nodes

Each bootstrap node carries one prose document form as a single LLM output, reviewed as a unit, and its content is immutable after first approval. Bootstrap nodes are the system's commitment points: when the user approves a bootstrap, they are approving the shape of everything that gets minted from it.

- `expansion_*` — feature expansion. Reviewed once, mints `feat_*` **and optionally `vocab_*` nodes** from a sibling `<vocabulary>` section of the expansion output. Project-level vocab has `parent_id = null`; feature-local vocab is minted with `parent_id` resolved to the appropriate feature's id via the mint-time alias map. Singleton per project. See A.1.12.
- `reqs_*` — top-level requirements. Reviewed once, mints top-level `resp_*` plus `feat → resp` decomposition edges. Singleton per project.
- `sysarch_*` — system architecture. Reviewed once, mints top-level `comp_*` nodes plus top-level `policy_*` nodes plus dependency edges plus domain-parent edges plus a `subreqs_*` bootstrap per top-level component plus the top-level techspec, pubapi, privapi fragments for each component. Singleton per project.
- `subreqs_*` — subrequirements, one per top-level component. Reviewed once, mints subresp `resp_*` plus `top_level_resp → subresp` decomposition edges. Not a singleton.
- `manifest_*` — file territory manifest. Singleton per project. Minted by code-generation passes, regenerated as the component tree reshapes.

**Post-approval, bootstrap nodes are read-only editing surfaces.** Incremental edits happen on the minted children, not by re-editing the bootstrap prose. The bootstrap node stays in the event log as a historical artifact; re-running cold-start is an administrative operation (A.21.4), not a routine edit.

### A.4.3 Change plans

A change plan is a reviewable prose artifact produced by a flow run at every tier the flow touches. Its job is to let the user agree on *what* the flow intends at each level before the regen at that level commits.

**Lifecycle.** Each change plan goes through draft → AI self-review → human review → approved states identical to a bootstrap node. Rejection feedback flows into a regen of the change plan itself. Once approved, the change plan is consumed by the regen pass at its tier as prompt context.

**What it contains.** A prose description of the changes at the tier it's for. For a feature request that touches the sysarch, a system-level change plan says "the billing feature expansion adds two top-level responsibilities; I propose minting one new top-level component (Billing), adding a dependency edge from Auth to Billing, and flagging two existing top-level policies as applicable to the new component." For a component the request touches, a component-level change plan says "this component needs a new subresponsibility for invoice rendering, which I'll add as a new subcomponent alongside the existing ones; its pubapi gains an `invoice_render` method; no new policies are needed."

**What it does not contain.** Code. Structured IDs for things that haven't been minted yet. Anything below prose reasoning. The change plan is the *intent*; the regen is the *mechanism*. The change plan isn't expected to list every byte of the downstream diff — it lists the shape of the changes so a reviewer can decide whether the flow's interpretation matches what they meant.

**Not structural.** A change plan is not a node in the dependency graph. Nothing refers to it by dep edge, no fragment transcludes from it, and it doesn't appear in the live DAG view that shows the component tree. It exists in a parallel review surface attached to the flow run, and it exists in the event log indefinitely as provenance. Users who ask "why did this regen happen, and what did we agree on?" can pull the change plan for that tier at that flow run and read it.

**Persistence.** Change plans persist in the event log forever. They're cheap to keep, they compose with the event log to give a complete answer to "what was the design intent at this moment in history," and deleting them would erase real audit value. The UI for browsing change plans is treated as a separable concern — the initial version may show them only in the context of a specific flow run's detail view, with a cross-project "all change plans" list deferred until there's a concrete use case for it.

**Not in the live DAG view.** The decomposition graph, component tree, and other structural visualizations do not display change plans. They are visible in flow-run detail views and in per-node provenance lookups. This keeps the structural view clean and ensures change plans don't clutter the primary editing surface.



## A.5 Review and approval

Every artifact produced by the system — bootstrap node, fragment, arch doc, change plan, impl doc, plan node, code diff — goes through review. The system provides two review surfaces, one for **model artifacts** (markdown-style rendering with inline + summary comments, version diffs, feedback panel) and one for **code** (file-level diff, inline review comments, CI status), but both use the same underlying status model and workflow.

### A.5.1 Review paths

**Model artifacts** follow this chain:

1. **AI self-review** — The generating handler produces an output, then runs a short self-review pass against structured criteria (quality score, recommendation, notes). If revision is recommended, the system automatically regenerates incorporating the self-review feedback, up to a configurable loop limit.
2. **Human review** — After AI self-review, artifacts enter an `awaiting_review` status. Humans review with **inline comments** anchored to specific sections (or specific lines inside a fragment) and **summary feedback** that captures cross-cutting concerns. Rejection feedback — both inline and summary — is included in a subsequent AI revision pass. Location-anchored feedback gives the AI much better signal about what to change than unstructured text alone.

**Code artifacts** (leaf-level PRs and plan-driven code diffs) follow a parallel path:

1. **AI code review** — The AI reviews generated code and posts inline comments tied to file paths and line numbers.
2. **CI loop** — CI results feed back into the generation loop. CI failure is not treated as "a bug to fix" — it means the system generated incorrect code and should retry with the error output as additional context. This is a first-class concept in the state machine (A.5.5), not an edge case.
3. **Human code review** — After AI review and CI pass, the PR enters `awaiting_review` for human review via Catapult's code review UI. Code review uses the same inline + summary feedback model as model-artifact review.

### A.5.2 Deferred feedback

Users can leave inline comments and summary feedback on **any node at any time**, not just nodes currently awaiting review. This feedback accumulates as pending and is automatically included in the prompt context the next time that node is regenerated by any flow.

This is the lightweight alternative to kicking off a full flow every time someone notices something. When working deep in the tree reveals that an upstream node should incorporate a new consideration, a user can leave a comment on the upstream node and move on — the comment waits until the next flow touches that node, at which point the regen picks it up automatically. Multiple deferred comments from multiple users can accumulate across any number of nodes. Deferred feedback does not trigger regeneration on its own; it waits until the node is next touched by a flow.

**Comment lifecycle.** All comments — inline review feedback, summary feedback, and deferred feedback — can be edited or deleted by their author after posting. Edits and deletions are recorded in the event log (the original content is preserved in history, not destroyed). Comments that have already been consumed by a regeneration pass are marked as such; deleting a consumed comment does not undo the regen it influenced. Pending (unconsumed) comments can be freely edited or deleted before the next regen picks them up.

**Feedback visibility.** Each node in the DAG visualization displays a pending feedback counter (badge). Counters roll up — a component shows the sum of its own pending feedback plus all its children's. This gives users an at-a-glance view of where feedback has accumulated across the tree, signaling where attention is needed.

### A.5.3 Collaborative discussions

Two conversation modes share the same underlying chat infrastructure (A.19):

- **Private AI chat** — per-user, per-project. A single user conversing with the AI (David) about the project, visible only to that user.
- **Collaborative discussions** — threaded conversations attached to a specific artifact (model artifact or code PR) during the review workflow. Team-visible — all project members with access to the artifact can read and participate. Messages are attributed to their author. Team members can @mention the AI as **@david** in a discussion thread; David responds in-thread with citations, visible to all participants. Discussion threads can culminate in review actions (approve, reject with feedback, request changes) attributed to the acting user.

Discussions persist alongside the artifact's review history. Unlike private chat, discussions are part of the artifact's provenance trail — future reviewers and the AI itself can reference prior discussion threads to understand why decisions were made.

### A.5.4 Ownership, routing, and review SLA

Review routing consults the scoped-role system (A.14.2). Each artifact sits inside some component's subtree (or, for project-level artifacts like the expansion bootstrap, sits at project scope). Review notifications route to whoever holds the `owner` role at the narrowest scope covering the artifact.

**Review type routing.** Different artifact types can be configured to require additional reviewers beyond the default owner, per project:

- **Architecture docs** → component owner + optionally an architect-role holder
- **Change plans** → component owner by default
- **Plans** → component owner
- **Code PRs** → component owner + optionally any team member with relevant domain expertise
- **Fan-out approvals** → parent component's owner (the person who owns the level above decides the decomposition and assigns ownership of new children)

A second reviewer can be optionally required per artifact type via project configuration.

**Notifications.** Reviews are the pipeline's bottleneck. Notifications are **batched**: "You have 4 architecture docs ready for review in the Authentication component" is one notification, not four. Channels include in-app at minimum, with webhook support (Slack / Teams / email) configurable per user.

Each user has a **review queue** — a unified view of all artifacts awaiting their review across all projects, with age, priority, and scope indicators.

**SLA and escalation.** Configurable review timeout per project:

1. After the first timeout: reminder notification to the assigned reviewer.
2. After a second timeout: escalate to the parent component's owner or project admin.
3. Optionally (off by default): auto-approve with a "flagged for post-hoc review" marker after a third timeout.

**Delegation.** Owners can reassign a specific review to another team member, delegate their entire component scope to someone else (temporary or permanent), or split ownership within their subtree (e.g., "I own this component but delegate the database subcomponent to Bob"). Delegation is represented as scoped-role assignments; the delegating user's role binding is narrowed or transferred as appropriate.

### A.5.5 Status chains

**Model artifacts:**

```
pending → generating → ai_reviewing → awaiting_review → approved / rejected / stale
```

**Code artifacts:**

```
pending → generating → ai_reviewing → ci_validating → awaiting_review → approved / rejected / stale
```

The `ci_validating` status is specific to code artifacts and represents the CI loop (A.21.7). Nodes cycle between `ci_validating` and `generating` on CI failure until the retry limit is reached. Projects without CI configured skip `ci_validating` entirely.

Rejecting an artifact marks its downstream dependents `stale`, which the scheduler picks up as candidates for regen.

### A.5.6 Review granularity and batching

Review gates are configurable: per-node, per-tier, leaves-only, or fully automatic with the destructive-operation carve-out (A.3.3) as a hard override. The default is sensible ("review fan-out and destructive ops, auto-approve everything else at the node level") but the user controls it.

The intended review workflow is **batched**: a flow run produces N artifacts, pauses for human review of that batch, the reviewer reads and leaves feedback on some or all of them, rejected artifacts and their downstream dependents regenerate as a sub-run incorporating the feedback, and once the sub-run completes, the parent flow resumes and produces the next batch. This produce-review-regenerate cycle repeats through the flow.

### A.5.7 Restart semantics

Flow runs support four restart granularities:

- **Node-level** — Regenerate a single node's output; downstream nodes are marked stale and the scheduler picks them up.
- **Tier-level** — Restart an entire tier (for example, regenerate every component architecture doc).
- **Flow-level** — Restart the entire flow from input expansion.
- **Partial retry** — Retry only failed or rejected nodes within a tier, leaving approved nodes intact.

Each restart option clearly communicates what gets invalidated in the UI so the user knows what they're signing up for.



## A.6 Flow lobby

Proposed flows do not execute immediately. They enter a **lobby** where they can be reviewed, prioritized, and queued by the user before execution begins.

### A.6.1 Lobby behavior

- All AI-initiated flows (from chat suggestions made via @david or equivalent) go to the lobby, never straight to execution.
- User-initiated flows can be sent to the lobby or executed immediately, at the user's choice. The lobby is not just for AI proposals — humans use it to queue up work they want done but not right now.
- The lobby displays pending flows with their description, estimated scope (which components would be affected), the triggering context (chat conversation, user request), and the proposed flow type (scaffolding, feature, refactor, bug-fix).
- Users can reorder, approve, reject, or modify proposed flows in the lobby before they are queued for execution.
- The lobby respects the one-active-flow-per-project constraint (A.7) — approving a flow from the lobby queues it behind any currently running flow.
- A **cross-project lobby view** shows all pending flows across all projects the user has access to, so a team lead can prioritize work across multiple projects from a single screen.

### A.6.2 AI as read-only proposer

The chat interface (A.19) and any other AI-driven analysis operates in **read-only mode** with respect to the pipeline. It can:

- Read all model state, code, events, and pipeline status
- Propose flows (which go to the lobby)
- Answer questions and trace provenance

It cannot:

- Directly start flows, modify model state, or change pipeline state
- Bypass the lobby to execute changes

This ensures humans remain in control of what work actually happens, while the AI can freely analyze and suggest.

## A.7 Concurrency and locking

The system uses **pessimistic locking** at the project level. Only one flow run or sub-run may be active per project at a time. This dramatically simplifies the concurrency story:

- No two flows can edit the same component simultaneously within a project.
- Sub-runs pause their parent, so there is no concurrent modification within a single project.
- Lock acquisition is coarse — per project, not per node — because fine-grained locking introduces deadlocks and adds complexity the current scale doesn't need.
- Locks are released on run completion, failure, or a configurable timeout.
- Different projects run concurrently — the single-active-flow constraint is per project, not global.

Within a flow, non-dependent nodes in the same tier can execute in parallel subject to the LLM concurrency limit (A.21.13). Parallelism is managed by the scheduler, which respects the limit when enqueuing jobs.

## A.8 Resumability and recoverability

- If a flow fails at any node, it can resume from the point of failure without re-running completed nodes. Completed nodes are identified by their presence in the event log; resumption is a matter of the scheduler re-querying state and picking up any work that the failure left incomplete.
- Completed nodes are **idempotent on re-run** — re-running a completed node produces a new version only if the output differs from the current state. Identical output is a no-op at the reducer level (same content → same projection → no new projection delta).
- All state changes are recorded as events, enabling replay and recovery by design, not as a bolt-on.
- Locks are automatically released on failure with a configurable timeout.
- **Reconciliation on startup** (A.21.11) is the mechanism that handles crash recovery at the process level: rebuild projections from the event log, detect orphaned executions, complete zombie runs, cancel stale jobs.

## A.9 Document storage model

**There is no git mirror of model state.** The event log plus the projection tables are the authoritative store for every design entity, every fragment, every draft, every event, every change plan, every comment, every review action. Documents the user sees (architecture pages, diff views, review panels) are **derived views** of the model — computed on demand from the event log and the projections.

This is a deliberate simplification from the catapult v1 model, which mirrored documents into git at review boundaries. The v2 model treats the event log itself as the history: every state change is a recorded event, version diffs are computed by walking the log, "what did this node look like at time T" is a projection query, and there's nothing a git mirror would add that the event log doesn't already provide natively.

Consequences:

- No "commit at review boundary" concept for model artifacts.
- No run-branch / component-branch / subcomponent-branch hierarchy for documents.
- No "this node has a markdown file in git" concept. The markdown is rendered from the model.
- Export is still possible (A.20.1) — an exporter walks the projection and emits markdown files to a directory, producing a fully-formed snapshot of the project's design state at a given point in time. But this is an *export*, not the authoritative store.
- Full audit history is in the event log, queryable by admins and used by the provenance chain (A.20.6).

**Git is still present in the system for code.** Generated code ships as commits against a real repository. The code side of the git story lives in A.10, and it is meaningfully narrower than catapult v1's git strategy because it only concerns code shipping, not document storage.

## A.10 Git for code shipping

Catapult generates code as a final leaf pass (A.3.1 step 11) and the generated code ships via git commits against a target repository. Every Catapult instance includes a **bundled gitea sidecar** that serves as the local git substrate — catapult always commits to gitea, and an optional **external forge plugin layer** pushes approved branches to wherever the user's team actually reviews code (GitHub, GitLab, a self-hosted gitea, or any other supported forge). For the MVP, all leaves within a project target a single repository (monorepo assumption), and the `{repository, folder}` territory mapping (A.1.11) defines which leaf owns which folder. Multi-repo is a post-MVP extension; the data model supports it but the flow orchestration and PR composition assume one repo.

### A.10.1 Local git substrate: bundled gitea

Every Catapult instance runs a gitea sidecar that holds the authoritative local copy of every project's code repository, every flow run's branch hierarchy, and every approved leaf commit. The gitea sidecar is bundled: in a hosted deployment it's a sidecar container, in a self-hosted install it's a service running alongside the catapult application. A catapult instance is never without its gitea — there is no "bring your own local git" mode.

This commitment exists for three reasons:

- **Thread safety and correctness.** The git CLI is not thread-safe, and native Elixir git libraries are immature. Gitea exposes a stable HTTP API that is thread-safe by design and battle-tested under concurrent load. Routing every write through gitea's API means catapult's git-touching code never has to reason about working-tree locks, index corruption, or race conditions between concurrent branch operations.
- **Single source of truth for what catapult did.** Gitea holds an immutable, event-ordered record of every commit catapult ever authored, including commits from flow runs that were rolled back, discarded, or superseded. This is the git analog of the event log — it can be replayed, audited, or diffed against any prior state. If an external forge rewrites or removes history, the local gitea copy is still authoritative for "what catapult actually generated."
- **Offline and airgapped operation.** An instance with no outbound network access is a fully functional catapult instance as long as its local gitea is reachable. Code shipping degrades to "commits land in local gitea and wait for an external forge push when connectivity returns"; everything else works unchanged. This matters for enterprise self-hosted deployments where the common case is restricted network egress.

Catapult's git-touching code is written against gitea's API, not against local git commands. There is no `git` subprocess anywhere in the hot path. Bundle import (A.11.5) reuses the same gitea substrate for the same reasons — one substrate, one code path, one set of operational concerns.

### A.10.2 External forge integration via plugin adapters

Users who want their code to land on an external forge (GitHub, GitLab, a different self-hosted gitea, Bitbucket, raw git-over-ssh, etc.) configure a **forge adapter** at the project or instance scope. The adapter is a small plugin with a fixed contract: push a branch, create a PR, update a PR's status, read inbound webhooks. That's the full surface — roughly five methods. Adapters do not touch local repository state, do not run git commands, and do not implement their own commit authoring logic. All of that lives in the gitea substrate.

The adapter contract is narrow on purpose. A project using the GitHub adapter works as follows:

1. Catapult generates code and commits it to the local gitea. The local gitea is the source of truth for what catapult generated.
2. When a flow run's leaf commits are approved, catapult invokes the adapter's `push_branch` method to mirror the branch from local gitea to GitHub.
3. When a PR is ready for review, catapult invokes `create_pr` on the adapter, passing the branch names and PR metadata. The PR lives on GitHub; reviews and merges happen there.
4. GitHub webhooks notify catapult of merges, closes, and status changes via the adapter's `read_webhooks` method. Catapult reflects the state changes in its event log.

A project with **no forge adapter configured** still works end-to-end. Leaf commits land in the local gitea, PRs are created on the local gitea, reviews happen in the local gitea's UI, and merges land on local gitea branches. Users who don't care about external forges get a complete product without touching the adapter layer.

**Adapter surface, explicit contract:**

- `push_branch(source_ref, target_branch_name)` — mirror a branch from local gitea to the external forge.
- `create_pr(source_branch, target_branch, title, body)` — create a pull request on the external forge.
- `update_pr(pr_id, status, body?)` — update PR metadata (for example, mark ready-for-review or append a comment).
- `read_webhooks()` — consume inbound webhook events (merge, close, review-requested, check-failed) and emit catapult-shaped state-change events.
- `delete_branch(branch_name)` — clean up branches after merges.

That's the whole contract. A new adapter is ~200 lines of Elixir, tested against a mock external forge, with no entanglement in catapult's local git logic. Bundled adapters for MVP: **gitea** (trivial, since the substrate is already gitea) and **GitHub**. GitLab and others are post-MVP but unblocked by the architecture.

### A.10.3 One commit per leaf

Each `impl_*` leaf produces a single commit per flow run. The commit is scoped to the leaf's territory (folder) and contains only files that belong to that leaf. Cross-leaf changes — files that touch two territories — are a manifest-level error surfaced in the admin tools, because the territory rule is what keeps generation parallelizable and leaf-scoped.

### A.10.4 Configurable PR granularity

PR granularity is configurable per project to one of three levels: **system**, **component**, or **subcomponent**.

- **System level** (default) — One PR for the entire flow run. All leaf commits compose into a single PR against main.
- **Component level** — One PR per component. Each component's leaf commits compose into a PR against the run branch.
- **Subcomponent level** — One PR per subcomponent. Each subcomponent's leaf commits compose into a PR against the component branch.

### A.10.5 Branch hierarchy

Flow runs use a **feature branch hierarchy** that mirrors the component tree:

```
main
  └── run-branch (flow run)
       ├── component-a-branch
       │    ├── subcomponent-a1-branch (leaf commits)
       │    └── subcomponent-a2-branch (leaf commits)
       └── component-b-branch
            └── subcomponent-b1-branch (leaf commits)
```

Code PRs are created at whichever level the project's PR granularity is configured to. Review flows upward through the branch hierarchy: subcomponent branches merge into component branches, component branches merge into the run branch, and the run branch merges into main. Catapult controls the review order and communicates which branches are ready in what sequence. The branch hierarchy lives in the local gitea substrate; external forge adapters mirror whichever branches the project's PR granularity requires.

### A.10.6 Blocking PR rule

If any outstanding PRs exist for a project from a prior flow run, new flows cannot start. All PRs from the prior run must be merged or closed before a new flow begins. This prevents the model from drifting out of sync with the codebase. Sub-runs are exempt from this rule — they contribute to their parent flow's branch hierarchy and exist precisely to handle mid-flow corrections.

### A.10.7 Git is only for code, not for design

A project without code generation (design-only projects, hypothetical-future-project explorations, documentation-only workloads) does not need a code repository at all. The structured model is the entire artifact. The code-shipping layer is optional per project — enable it when you want code shipping, skip it otherwise. The local gitea substrate is still used for bundle storage (A.11.5) even in design-only projects; a design-only project simply has no code repository registered under its name.

## A.11 Prompt and DAG configuration

**Design commitment: the structure is data, not code.** Per-tier generation prompts, the generation order itself, validator schemas, projection-source parsers, and the scheduler's query rules are all loadable configuration rather than hardcoded Python/Elixir modules. A project can override any of it, and a bundle — a complete configuration for a particular tech stack or workflow style — can be imported from an external source and applied to a project.

### A.11.1 What is configurable

- **Per-tier prompts.** System message, user-prompt template, context-assembly template, retry-on-parse-error instructions, AI-self-review criteria. Every generation tier (expansion, reqs, sysarch, subreqs, comparch, subcomparch, impl, plan, code) has a prompt bundle. Change plans and diagnosis nodes have their own prompt bundles.
- **Validator schemas.** The parseable-arch-doc structure is data: section order, allowed children, fragment kinds, foundation rules, and dep-edge scoping are all specified in configuration, not hardcoded in a validator module. Adding a new fragment kind is a configuration edit and a migration, not a code change.
- **Generation order.** The cold-start topological order (A.3.1) is configurable — a project could insert a new tier, reorder existing tiers, or replace a tier with a different shape.
- **Scheduler queries.** The state queries that drive the state-driven scheduler (A.3.2) are data. Adding a new kind of regen trigger is a configuration edit, not a code change in the scheduler module.
- **Edge type vocabulary.** The closed set of edge types (A.1.3) is configurable with appropriate migration support — adding a new edge type is explicit work, but it's possible without modifying the core codebase.

### A.11.2 Bundles

Configuration is packaged as **bundles** — git repositories containing the full set of prompts, validators, generation order, and scheduler queries for a particular workflow style, plus a manifest declaring the bundle's level, name, and version. Bundle examples: "Elixir/Phoenix scaffolding," "Python FastAPI backend," "React frontend feature request," "Infrastructure-as-code Terraform." A bundle represents a complete configuration; projects inherit from a single bundle with per-project overrides layered on top.

**Instance-level bundle library.** Each Catapult instance ships with a bundle library — a gitea namespace containing every bundle approved for use on the instance. The library is part of the v1 commitment: instance admins curate the library, and projects choose their bundle from the library rather than importing one ad-hoc per project. Self-hosted deployments curate their own library; hosted deployments start from a vendor-maintained default set. New projects inherit from the instance default bundle (configurable per-instance) unless the project owner explicitly chooses a different library bundle at project creation.

**Curation and security.** Bundles are a prompt-injection and supply-chain attack surface — a malicious bundle could embed instructions that exfiltrate model content, inject backdoors into generated code, or manipulate the review flow. Curation is therefore mandatory, and the mechanism is **mirror-based approval**: admins import a bundle by mirroring its upstream git repository into the instance gitea's bundle namespace, and the mirror's existence is the approval. Revocation is deleting the mirror. Version bumps are admin-initiated fetches against the upstream, with explicit approval of the new tag before projects can bump. This reuses gitea primitives (fork, mirror, fetch-upstream) rather than inventing a parallel approvals subsystem; the instance admin UI for bundles is the gitea admin UI, with a thin catapult-side view that reads the namespace and surfaces manifest metadata.

### A.11.3 Per-project overrides

A project inherits its full configuration from a bundle (or the instance default) and can override any specific piece at the project level. Override granularity:

- **Per-tier prompt override** — the user edits a specific tier's prompt while inheriting everything else from the bundle.
- **Per-model override** — the user sets a different model or temperature for a specific tier.
- **Per-node override** — the user overrides a specific field on a specific node's regen (rare, mostly a debugging tool).

Model and temperature are configurable at three levels with standard "most-specific wins" fallback: project default, per-tier default, per-node override.

### A.11.4 Levels of abstraction

Bundles span a wide range of ambition, from "swap the prompts on the default flow" all the way to "describe a completely different design system on top of the same engine." Trying to design for the most ambitious case from day one would force every bundle author to make decisions they don't have context for; trying to lock in only the simplest case would paint the engine into a corner. The bundle system is therefore organized into **four levels of abstraction**, each strictly extending the previous one and each making explicit which engine guarantees the bundle inherits and which it must take responsibility for.

A bundle declares its level. The instance approval flow (A.11.2) treats higher levels as higher-risk: a Level 0 bundle only changes prose, a Level 3 bundle can introduce a totally new tier hierarchy with its own propagation rules.

**Level 0 — prompt overrides only.** The bundle ships replacement prompt templates for the existing tiers. Tier vocabulary, edge types, validators, generation order, scheduler queries, depth caps, foundation rules, and the approval-gate model all come from the engine's defaults unchanged. A Level 0 bundle is the right shape for "we want to use the default v2 flow, but tune the tone and emphasis for our team's tech stack." The author writes prose and inherits everything else.

**Level 1 — prompts + grammars.** Adds the ability to redefine the parseable-arch-doc grammar for any tier — section order, allowed children, fragment kinds — by shipping a validator schema alongside the prompt templates. The engine still owns the tier vocabulary, the cold-start order, the foundation rule, the depth cap, and the propagation model. A Level 1 bundle is the right shape for "we want a different shape of architecture document at the comparch tier, but the tier still means what it means." Existing Phase 4/5 carve-outs (foundation components don't decompose, two-level cap on subcomponent depth) are still enforced by the engine, so a Level 1 bundle author cannot accidentally break them.

**Level 2 — prompts + grammars + declarative mint specs.** Adds the ability to redefine how a tier's mint handler reads its source content and emits events. The mint logic is expressed as a small declarative pipeline (walk this XML structure, emit one `NodeCreated` per matching element with these attributes, emit one `EdgeCreated` per cross-reference, populate the alias→id map this way) rather than as Python code. The engine still owns the event vocabulary, the reducer invariants, the approval gates, and the scheduler. A Level 2 bundle can introduce a new tier name, point its prompts at the new validator, and have the mint handler do the right thing without writing any handler code. The bundle author is responsible for the bundle's own internal consistency, but cannot violate engine-level invariants because the reducer rejects events that would.

**Level 3 — fully data-driven tier hierarchies.** Adds the ability to redefine the cold-start generation order, the scheduler queries, and the propagation rules. A Level 3 bundle can describe a completely different layered design system — narrative writing with character / setting / scene tiers, hardware design with subsystem / component / interconnect tiers, anything with the right shape — and ship it as a single configuration object. The engine still owns event sourcing, the reducer-projection model, the change-plan loop, and the review/approval flow, but the *structure* of the DAG is up to the bundle.

**Inheritance promises** (these are the contract the engine makes to bundle authors at each level):

| Promise | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| Tier vocabulary fixed | ✓ | ✓ | extends | replaces |
| Edge type vocabulary fixed | ✓ | ✓ | extends | replaces |
| Foundation-don't-nest rule enforced | ✓ | ✓ | ✓ | bundle-owned |
| Subcomponent depth cap enforced | ✓ | ✓ | ✓ | bundle-owned |
| 1:1 leaf:resp:component mapping | ✓ | ✓ | ✓ | bundle-owned |
| Approval gates on destructive ops | ✓ | ✓ | ✓ | ✓ |
| Event sourcing + reducer model | ✓ | ✓ | ✓ | ✓ |
| Change plans for structural edits | ✓ | ✓ | ✓ | ✓ |
| Review/feedback/regen loop | ✓ | ✓ | ✓ | ✓ |

Promises that survive across all four levels are **engine-level invariants** — they are properties of the Catapult execution model itself, not of any particular design system. Promises that move from "enforced" at L0/L1 to "bundle-owned" at L3 are **default-system invariants** — they are properties of the v2 catapult-spec design system, hard-won by workshopping, but not properties of every possible layered design system.

**MVP commitment: Level 2.** The difference between a tool and a platform is whether a bundle author can introduce a new tier without filing a platform feature request, and that capability lives at Level 2. L0 and L1 are useful intermediate stepping stones during implementation — the code refactor naturally lands L0 first (prompts become data), then L1 (grammars become data), then L2 (mint specs become data) — but v1 ships with the L2 contract committed to. Level 3 remains a long-term north star; it requires the scheduler and propagation rules themselves to become data, which is a much larger investment and one we should only pay once enough L2 bundles are in the wild to know what L3 actually needs to express. Shipping L2 at v1 also pins the refactor scope: the engine's existing handlers get restructured into the closed operation vocabulary (A.11.6) so that the default flow and any L2 bundle share the same execution substrate.

One thing L2 **does not** unlock, and which stays engine-owned at all levels below L3: the scheduler queries that drive state-driven generation (A.3.2). L2 bundles define *what* a tier is and *how* it mints nodes; they do not get to define *when* a tier fires. New tiers introduced by an L2 bundle ride the same propagation primitives as the default flow — draft approved triggers downstream regen, fragment changed marks dependents stale, and so on — and the bundle author's job is to declare which of those triggers their tier cares about. This is a useful constraint, not a limitation: it forces new tiers to fit the propagation model, which keeps bundles from drifting into bespoke scheduling logic that the engine can't reason about.

### A.11.5 Distribution and storage

Bundles are distributed as **git repositories**, stored in the **instance's gitea substrate** (A.10.1), and resolved to specific commits when a project picks a version. A bundle is a directory of YAML/JSON/text files (prompts as text, grammars as YAML, mint specs as YAML, scheduler queries as YAML at L3) plus a manifest declaring the bundle's level, name, version, and dependencies. The instance's bundle library is a gitea namespace (for example, `bundles/fastapi-backend`, `bundles/react-frontend`), and each namespace entry is a gitea mirror of the bundle author's upstream repository.

**Why gitea-as-substrate rather than git-clone-anywhere.** Catapult already runs a gitea sidecar for code shipping (A.10.1). Reusing it for bundle storage means one substrate, one code path, one backup story, and one operational model — no second-class registry or filesystem-cache layer to build and maintain. The properties we get for free by routing bundles through gitea are substantial:

- **Instance bundle library = gitea namespace.** The set of bundles available to projects is literally the set of repositories in the `bundles/*` gitea namespace. No separate approvals table, no separate admin UI, no separate state machine. Admins manage the library with the gitea admin UI they already use for code repositories.
- **Approval = mirror.** Importing a bundle into the library is creating a gitea mirror of the upstream. Revoking a bundle is deleting the mirror. Version bumps are admin-initiated fetch-upstream operations followed by explicit tag approval. This is exactly the primitive gitea is built for, and it gives admins a one-screen workflow for the full lifecycle.
- **Version pinning is commit SHAs.** A project declares "I'm on bundle `fastapi-backend@v1.2.3`" and that resolves to a specific commit in the instance gitea. That commit is guaranteed to remain resolvable for the life of the instance, because the instance owns the mirror. Upstream rewrites, force-pushes, or repository deletions cannot invalidate a project's pinned version.
- **Supply-chain auditing is automatic.** Every bundle version a project has ever used is an immutable commit in the instance gitea. Security review of what generated a given flow run is a git log walk against the instance gitea, not a race against external forge history.
- **Offline and airgapped deployments work.** Once bundles are mirrored into the instance gitea, the instance does not need outbound network access to resolve, load, or apply them. Air-gapped environments import bundles via tarball → local gitea repository, and the rest of the system works unchanged.
- **Caching and latency.** Bundle loads hit a local gitea, not a remote forge. Nothing in the hot path of project creation or flow execution waits on external network I/O.

**Bundle authors publish wherever they want.** The upstream source of a bundle can be GitHub, Codeberg, a self-hosted gitea, a tarball on a webserver, or an internal git forge at a customer's organization. The instance admin imports by specifying the upstream URL when creating the mirror, and gitea handles the rest (`POST /repos/migrate` with `mirror=true`). There is no requirement that bundle authors use any particular hosting, only that the bundle be reachable by git clone when the admin imports it.

**What is still explicitly out of scope** for the bundle system MVP, even with the gitea substrate in place:

- **Cross-instance discovery.** Within an instance, discovery is the gitea bundle namespace — users can browse it and see everything approved. Cross-instance discovery ("which bundles are good and who uses them") is a community problem (curated lists, blog posts, shared instance snapshots) rather than a platform one. An opt-in public registry of bundle upstreams can be layered on later without changing the storage mechanism.
- **Composition.** A project inherits from exactly one bundle with per-project overrides on top. There is no support for combining two bundles into one (no "Python FastAPI backend" + "React frontend" merge). Composition requires conflict resolution between two bundles that override the same tier's prompt, and the right design is unclear without real-world examples to test against. Multi-bundle projects can be revisited once single-bundle projects are working.
- **Runtime patching.** Once a project has imported a bundle, schema changes to that bundle (new tiers, new fragment kinds, new edge types) require a project-level migration. There is no auto-migration of in-flight projects when a bundle's grammar evolves. The engine surfaces a schema-version mismatch as an explicit error, and the project owner runs a migration handler.

### A.11.6 The closed vocabulary of operations

A key insight from designing the four levels: **the engine's existing handlers can be written entirely in terms of a small closed vocabulary of operations.** Walking a node's subtree, walking edges of a particular type, emitting a `NodeCreated` event, emitting an `EdgeCreated` event, building a name→id alias map, cross-referencing two collections by alias, rendering a template with a context dictionary, querying nodes by tier and parent — these eight or so operations cover every existing mint handler, every regen-context builder, and every scheduler trigger. Nothing in the v2 code (as of Phase 5.5) requires arbitrary Turing-complete logic.

This is what makes Levels 1 and 2 tractable: the bundle author isn't writing code, they're declaring *which* of these operations to apply, *to which* part of the parsed source content, *producing which* events. The DSL grammars at each level are small because the operation vocabulary is small. When the engine needs to grow a new operation (because some real-world bundle hits a wall), the operation is added to the closed vocabulary and every level above the change inherits it for free.

**Escape hatches** are bounded and explicit. A bundle that needs a custom validation invariant beyond what the grammar layer can express ships a small named function the engine knows how to call by name; the function lives in a per-instance allowlist and the instance admin signs off on it during bundle approval. Bundles that need cross-event coordination (deferred fan-out, custom edge propagation) declare named handlers in the same allowlist. The escape hatches are **not** "ship arbitrary Python in the bundle" — that would erase the security and reviewability benefits of declarative bundles. They are "ship a name; the engine looks up the name in an instance-controlled registry of approved code." This keeps bundle authoring in the data domain while still letting bundles reach for engine-level capabilities when the declarative layer falls short.

### A.11.7 Per-project overrides revisited

With the level model in mind, per-project overrides (A.11.3) become more precise. A project inherits a bundle at some level L; per-project overrides operate at the same level or below. A project on a Level 1 bundle can override prompts (Level 0 operation) and grammars (Level 1 operation), but cannot introduce new tiers (Level 2 operation) without first upgrading the project's bundle to Level 2. This protects the inheritance chain — a project author can't accidentally drop into a level the bundle author didn't sign up for.

Override storage is project-scoped: overrides live as event-sourced configuration entries in the project's event log, so they are versioned, reviewable, and replayable just like every other piece of project state. Reverting a per-project override is a normal event-stream operation, not a separate "config rollback" path.

### A.11.8 What is still TBD

Even with the L2 commitment, the gitea substrate, and the instance library all locked in for v1, a small number of mechanics are deferred to dedicated workshops:

- **Schema migration language.** When a bundle's grammar changes between versions, projects on the old version need a migration path. The migration runs as a normal event-sourced operation (emit corrective events that bring projection state to the new shape), but the *language* bundle authors use to describe the migration in the bundle itself is not yet specified. The first few migrations can be hand-written as one-off handlers; the declarative migration language is deferred until there are enough examples to generalize from.
- **Override expression syntax.** Per-project overrides could be expressed as JSON patches, full file replacements, key-value dicts, or a small templating language. The choice depends on what overrides actually look like in practice; deferred until L0 overrides are in use and we can see the shapes.
- **Bundle signing beyond mirror-based trust.** A.11.2's mirror-based approval model gives instance admins a manual trust decision without requiring cryptographic signing: the act of mirroring an upstream into the instance bundle namespace *is* the approval, and the mirror holds an immutable copy that cannot be rewritten by upstream. Cryptographic signing (sigstore, in-tree GPG, instance-managed key rings) makes the trust decision cheaper to propagate between instances and gives admins a machine-checkable provenance trail — valuable but not blocking for v1. Deferred until there are enough instances sharing bundles that manual trust decisions per instance become the bottleneck.

These TBD items are deliberately scoped *below* the level model, the gitea substrate, and the instance library, because those three are the promises bundle authors and instance admins reason about. The deferred items are implementation refinements that can land incrementally without invalidating bundles already in the wild, as long as the level boundaries, the storage model, and the inheritance contract stay stable.

## A.12 Credentials and token tracking

### A.12.1 BYO credentials

The system is **BYO LLM credentials** — customers supply their own API keys through the application, not through environment variables. Credentials are stored encrypted at rest using per-instance keys, never in plaintext. The LLM API traffic goes directly from Catapult's sandbox to the provider — the user's credentials pass through Catapult but are not inspected or reused for cross-user requests.

### A.12.2 Scoped credential assignment

Credentials can be assigned at three scopes, with most-specific-wins fallback:

- **Instance scope** — a default credential used by any project that doesn't override.
- **Project scope** — a project-specific credential that overrides the instance default for work done on that project.
- **User scope** — a per-user credential that overrides the project scope for work initiated by that user.

A generation call resolves credentials by checking user scope first, then project scope, then instance scope. This lets enterprise admins set a shared project credential for team work while allowing individual users to substitute their own credentials for personal exploration, and it lets single-user self-hosted deployments configure an instance default and forget about it.

Credentials are tied to the LLM provider and the model family — a single project may have multiple credential bindings if it uses multiple providers (for example, a main provider for generation and a smaller/cheaper provider for AI self-review). The credential scheme is provider-agnostic; adding a new provider is a matter of adding a provider adapter, not reworking the credentials layer.

### A.12.3 Token tracking

Token usage is tracked per node, per fragment or section where applicable, per flow run, and per project. Every LLM call records `(node_id, section, model, prompt_tokens, completion_tokens, timestamp)` synchronously as part of the job handler. Missing telemetry is treated as a generation failure for alerting purposes even though it doesn't fail the generation itself.

Telemetry data is **not part of the event log** — it's observability, not state — but it **is** surfaced in the UI alongside the artifacts it belongs to:

- Every node and every parseable section displays its most recent generation's token count in-place.
- The batched review UI shows aggregate token usage for the whole batch so the user can see "this review pass cost X tokens" at a glance.
- Per-project, per-component, and per-flow-run rollups are queryable from an admin endpoint.

The point is not cost discipline for the MVP — we have accepted that cost optimization is not an MVP goal. The point is making runaway prompt growth **immediately visible**. A regen that suddenly costs 5× what it cost yesterday is the signal that something is wrong with the prompt — too much sibling context, an uncontrolled dependency fan-out, a prompt template regression — and we want that signal visible at the UI the moment it happens, not after somebody bothers to look at a log.

### A.12.4 Cost projection — deferred

Model identifiers are recorded alongside token counts so that future cost projection can retrofit historical data. Cost projection (converting tokens to dollars for display in the UI) is a post-MVP feature; the tracking infrastructure is in place from day one.

## A.13 Real-time updates and external integration

### A.13.1 Live updates

All connected clients receive live updates when artifacts are generated, statuses change, or flows progress. DAG visualizations, status indicators, review queues, and artifact viewers update in real-time. Updates flow over WebSocket-based push channels scoped per project; a user viewing project A does not receive update traffic for project B unless they're also subscribed to B.

### A.13.2 External webhooks

Catapult emits webhook events for external integrations. Configurable per project, these webhooks notify external systems of significant pipeline events:

- Flow started, paused, completed, or failed
- Artifact ready for review (human review needed)
- Review SLA timeout exceeded
- PR created or merged
- Run completed with summary (components processed, artifacts generated, token usage)

Webhook payloads include enough context for external systems to take action (Slack notifications, CI dashboard updates, project-management tool integration) without needing to query Catapult's API. Webhook endpoints are configurable per project by admins.

### A.13.3 External API

Catapult exposes a programmatic API for external tooling. The API provides:

- **Read access** to all project state: structured model, flow status, event log, artifact content, review status, lobby contents, token usage.
- **Write access** to flow operations: propose flows to the lobby, leave deferred feedback, trigger actions permitted by the caller's role.

Authentication uses the same per-user credentials and scoped-role system as the web UI. Every API call is subject to the same permission checks as the equivalent UI action. The API enables custom dashboards, chat bots, project-management integrations (Jira, Linear), CI/CD pipeline queries, and third-party tooling built on Catapult's data model.

## A.14 Authentication and authorization

### A.14.1 Permission atoms

Authorization is **atom-based**, not role-based in the hardcoded sense. The system defines a closed vocabulary of **permission atoms** — discrete actions that can be individually granted or denied. Examples from the vocabulary:

- `flow.start`, `flow.cancel`, `flow.approve`
- `artifact.approve`, `artifact.reject`, `artifact.comment`, `artifact.defer_feedback`
- `prompt.edit`, `prompt.override`, `bundle.import`, `bundle.approve`
- `user.invite`, `user.remove`, `role.define`, `role.assign`
- `credentials.manage_instance`, `credentials.manage_project`, `credentials.manage_self`
- `owner.transfer`, `owner.delegate`
- `admin.prune`, `admin.force_restart`, `admin.reset_all`, `admin.force_sync`
- `chat.use`, `chat.propose_flow`, `chat.at_mention_david`

The atom vocabulary is extensible — adding a new feature means registering new atoms, not changing the auth model. Every action behind a permission check is gated on a specific atom, not a role. Changing what a role can do is a matter of recomposing atoms, not a code change.

### A.14.2 Roles as named atom sets with optional scope

A **role** is a named set of atoms, optionally scoped to a specific subtree. The system ships with preset roles — `admin`, `member`, `viewer`, `reviewer-only`, `prompt-maintainer`, `owner` — but these are convenience wrappers over the atom vocabulary, not hardcoded categories. Enterprise admins can define their own roles via the `role.define` atom.

**Scoped roles** pin a role assignment to a specific node's subtree. Permission checks against artifacts inside the scope consult the scoped role; artifacts outside the scope do not. The most common use is `owner` scoped to a specific component: the user holds `owner` with scope `comp_abc123`, and the atoms the owner role grants (approve, transfer, delegate, etc.) apply only within that component's subtree.

Scoped roles compose: a user can be `owner` of component A, `reviewer-only` of component B, and `admin` project-wide, all at once. Permission checks resolve by starting at the narrowest applicable scope and walking outward, with the first grant-or-deny decision winning.

### A.14.3 Preset roles

The system ships with these preset roles as convenience defaults. Enterprise admins can customize them or replace them entirely:

- **`admin`** (project scope) — every atom. Can invite users, define roles, approve bundles, manage credentials, run admin tools.
- **`member`** (project scope) — can start flows, review artifacts, edit prompts, comment, propose flows to the lobby. Cannot define roles, approve bundles, or use admin tools.
- **`viewer`** (project scope) — read-only plus commenting and deferred feedback. Cannot start flows or approve artifacts.
- **`reviewer-only`** (project scope) — can review and approve/reject artifacts, but cannot start flows or edit prompts. Useful for external reviewers who shouldn't drive work but should sign off on results.
- **`prompt-maintainer`** (project scope) — can edit prompts and import/approve bundles, but cannot start flows or approve artifacts. Useful for separating configuration work from operation work.
- **`owner`** (component scope) — the default reviewer for everything in the component's subtree. Granted via fan-out review or explicit assignment.

### A.14.4 Sessions and identity

- **Invite-based onboarding** with time-limited tokens.
- **Session management** — configurable session timeout, concurrent session limits, admin-initiated forced logout.
- **Auth audit log** — all authentication and authorization events logged separately from the pipeline event store: login, logout, failed login attempts, permission changes, role changes, invite creation and redemption, credential updates. Append-only, tamper-evident, queryable by admins.

### A.14.5 SSO and SAML

SSO and SAML are **in scope for the MVP**. Enterprise customers frequently require integration with their existing identity provider and cannot use standalone credentials for production work, so SSO integration ships from day one.

- **SSO flow** — a user authenticating via SSO lands in Catapult with an identity provided by their IdP. Catapult creates or updates the local user record keyed to the IdP-supplied identifier.
- **SAML assertion handling** — Catapult acts as a SAML Service Provider, consuming assertions from a configured Identity Provider. Assertion parsing includes signature verification and replay protection.
- **Group-to-role mapping** — IdP groups are mapped to Catapult preset roles (or custom roles) via an admin-configurable mapping table. A user's effective role set is the union of all roles mapped from their IdP group memberships. Group changes in the IdP propagate on next login.
- **JIT provisioning** — users authenticating via SSO for the first time are auto-provisioned with the role set derived from their IdP groups; no separate invite flow.
- **Session bridging** — SSO sessions map to local Catapult sessions with their own timeout. Logging out of Catapult invalidates the local session; it does not force SSO logout at the IdP (that's a global concern).
- **Multiple IdPs per instance** — supported, so a single Catapult instance can serve multiple organizations each with their own IdP.
- **BYO credentials compose with SSO** — SSO handles identity; BYO LLM credentials (A.12) handle LLM authentication. A user authenticated via SSO still supplies their own LLM credentials if the project is configured for user-scope credentials. The two layers are independent.

## A.15 Multi-project support

A single Catapult instance supports multiple independent projects. Each project has its own:

- Structured model, event log, and projections — fully isolated from other projects
- Repository (or repositories, post-MVP) for code shipping
- Bundle configuration (inheriting from instance defaults with per-project overrides)
- User memberships and scoped-role assignments
- Review queue, lobby, and SLA settings
- Credential bindings (optionally inheriting from instance-scope credentials)

**One active flow run per project at a time** (A.7); different projects run concurrently. The LLM concurrency limit (A.21.13) applies per-instance, so many parallel projects share the same pool of allowed concurrent LLM calls.

A user can be a member of many projects simultaneously, each with their own scoped role. The review queue UI unifies awaiting-review artifacts across every project the user has access to, with project-name breadcrumbs and priority indicators. The lobby has both a per-project view and a cross-project view (A.6.1) for tech leads who manage multiple projects from a single screen.

Project creation is an admin operation behind the `project.create` atom. A new project starts empty and picks up the instance's default bundle, default credentials, and default role preset list. The admin who creates the project is granted `admin` scope on that project by default.

## A.16 Bootstrap flow

A one-time flow for onboarding an existing codebase that already has design documents in the expected shape. The bootstrap flow takes:

- A codebase with documents matching the scaffolding flow's output shape (expansion, requirements, system architecture, subrequirements, component/subcomponent architecture docs, impl notes, plan artifacts) organized in the expected hierarchy
- The folder structure that maps each leaf to its territory

and reconstructs the structured model by parsing each incoming document into the same projection sources the cold-start flow would produce. The reducer then emits `NodeCreated` / `EdgeCreated` / `FragmentUpdated` events that populate the projection as if the nodes had been minted by the corresponding bootstrap nodes.

- **Synthesized baseline event** — a `ProjectBootstrapped` event (or equivalent) establishes the initial snapshot from the imported documents, so reconciliation (A.21.11) can rebuild projections from events without special-casing bootstrap.
- **Destructive to existing project state** — bootstrap can only run on a fresh project; it overwrites any existing model state.
- **Review records start fresh** from the point of bootstrap; prior review history in the source codebase is not migrated.
- **After bootstrap**, the project can use any standard flow (scaffolding regen, feature request, refactor, bug-fix propagation) to iterate on the imported model.

The bootstrap flow is how a team adopts Catapult on an existing project without rewriting the design from scratch. It is a one-time operation — once a project has been bootstrapped, incremental code and design changes flow through the normal flows.

## A.17 AI coding assistant integration

The coding portion of leaf execution — plan generation and code generation — is delegated to an AI coding assistant that has direct tool access to the project's repository. The assistant handles "how to change the code" against the actual codebase; the structured model provides "what needs to change."

- **Tool access** — the assistant can read, navigate, and modify files in the leaf's territory (A.1.11), subject to AI sandboxing (A.18). It has the same tools a human developer using an AI coding CLI would have, scoped to the leaf.
- **No separate code indexing** — the assistant uses its own tools to read code in context; Catapult does not maintain a separate AST index or code search layer. This keeps the code-side tooling decoupled from the design side and lets Catapult integrate with whatever coding assistant the project prefers.
- **Plan node as input** — the approved plan node is the contract between the design side and the coding assistant. The plan describes what changes are needed and why; the assistant reads the plan and executes it against the real code.
- **Code-level review feedback** comes back to the plan node as a follow-up if the generated code doesn't match the plan. CI failures (A.21.7) trigger regeneration of the plan or the code depending on the nature of the failure.
- **Multiple providers supported** — the coding assistant is behind an adapter interface. Claude Code, Cursor, Aider, or other tools can plug in via the adapter layer without changing the core model.

## A.18 AI sandboxing

All AI execution — coding assistants, document generation, chat responses, template prompts — runs in a sandboxed environment. The sandbox enforces:

- **Filesystem scoping** — coding assistants can only access files within the leaf's folder territory (A.1.11). A leaf for `src/auth/` cannot read or write files in `src/payments/`. Generation prompts for non-code artifacts have no filesystem access at all.
- **No arbitrary network access** — AI execution can reach the configured LLM API endpoint and nothing else. No outbound HTTP to arbitrary URLs, no DNS resolution of external hosts.
- **No credential access** — the sandbox cannot access stored credentials (LLM API keys, git tokens, user secrets). Credentials are injected by the orchestrator into the specific API calls that need them, never exposed to the AI's tool environment.
- **Resource limits** — CPU, memory, and execution time are bounded per node execution. A runaway generation cannot consume unbounded resources.
- **Template isolation** — bundle prompt templates can only access the context categories they are configured for (A.3.5). A template cannot override system-level safety prompts or modify its own execution parameters. This is the primary defense against prompt injection via malicious bundles.
- **No session persistence** — AI execution environments are reset between nodes; no state leaks from one generation to another beyond what's explicitly passed in via context.

Sandboxing is especially critical because the system runs untrusted LLM output on infrastructure the team controls. A compromised bundle or a maliciously-crafted prompt injection attempt must not be able to exfiltrate data, escalate privileges, or run arbitrary code.

## A.19 AI chat interface — David

A conversational AI assistant named **David** — as in David and Goliath, a small, well-aimed tool that helps small teams take on massive projects — scoped per project. David can answer questions about the codebase and its design graph, but operates in **read-only mode** with respect to the pipeline: it can analyze everything but cannot directly modify state, start flows, or change pipeline configuration. When David identifies issues or opportunities, it proposes flows that go to the flow lobby (A.6) for human prioritization. In collaborative discussions (A.5.3), team members invoke David via **@david**.

### A.19.1 Capabilities

- **Design Q&A** — "Why does the authentication component use session tokens instead of JWTs?" David retrieves relevant architecture docs, plans, and review feedback via the vector index and answers with citations to specific nodes and versions.
- **Codebase Q&A** — "How does the payment webhook handler work?" David uses the coding assistant's tools (A.17) to read and navigate the actual code, combining what it finds with the design graph context.
- **Provenance queries** — "Who approved the database schema change and why?" David queries the event log and review history to trace decisions back through their full chain.
- **Cross-cutting questions** — "Which components would be affected if we changed the user model?" David uses the dependency graph and component architecture docs to identify impact across the tree.
- **Flow proposals** — "This component's docs don't match the code I just saw." David can propose flows (feature request, refactor, bug-fix propagation) that are sent to the flow lobby for human review and prioritization. David never directly initiates execution.

### A.19.2 Review UI integration

David is context-aware of the user's current review state. When a user is reviewing an artifact, David:

- Knows which artifact is currently being reviewed and can answer questions about it without the user having to describe it
- Can explain why a particular design decision was made, trace the provenance of a change, or compare the current version against previous versions
- Can take review actions on behalf of the user — reject with feedback, approve, request changes — when explicitly asked. These are human review actions attributed to the user, not autonomous AI actions.
- Eliminates the need to copy-paste artifacts into a separate chat context to ask questions about them

### A.19.3 Context and scoping

David is scoped to a single project. It has access to:

- All model state (current versions, with ability to reference historical versions via the event log)
- The codebase via the coding assistant's tools
- The event log and review history
- The current pipeline state (runs, artifacts, lobby contents)
- The user's current review context (which artifact they're viewing, their position in the review queue)

Context assembly for chat queries uses the same vector retrieval and budget-based approach as pipeline execution (A.3.5), but with a query-driven retrieval strategy rather than a node-type-driven one.

### A.19.4 Conversation history

Private chat conversations are persisted per project, per user. Users can reference prior conversations. Conversations are not part of the event-sourced pipeline — they are a read-only interface over the project's state, stored separately from the pipeline event store.

### A.19.5 David is not proactive

David does not run background analysis, surface issues unprompted, or interrupt the user's workflow with suggestions. It responds to user questions, participates in collaborative discussions when @mentioned, and proposes flows when asked — but it does not watch for problems and raise them on its own. This is a deliberate scope narrowing from the catapult v1 concept: proactive AI suggestions sit uneasily with the "human is in control" commitment, and the review-queue + feedback-counter + lobby combination already gives users enough visibility into where attention is needed without a background daemon deciding what to flag.

## A.20 Adoption and trust

These requirements address the concerns of teams evaluating Catapult — particularly midsize engineering organizations that need to justify the investment and manage the risk of adopting a new workflow where an AI touches their design graph and their codebase.

### A.20.1 Portability and no lock-in

All project artifacts — structured model, code, event history — are exportable at any time. The export path walks the projection and emits a directory of markdown files (architecture docs, plans, policies, change plans, review history) alongside the code repository, producing a fully-formed snapshot of the project's design state at a given point in time.

If a team decides to stop using Catapult, they walk away with a set of markdown documents and a working code repository — no proprietary formats, no data trapped in the database. The export is deterministic and repeatable; running export twice against the same event-log offset produces byte-identical output.

### A.20.2 Graduated autonomy

The system supports a spectrum from fully supervised to fully autonomous. A team can start with every single node requiring human approval (treating Catapult as a "suggestion engine") and gradually increase auto-approval as trust builds. The spectrum is continuous — not a cliff between "manual" and "automatic." This is controlled via the auto-approval configuration (A.5.6) and review granularity settings. The destructive-operation carve-out (A.3.3) and the fan-out review rule (A.3.4) are hard overrides that cannot be bypassed by auto-approval — they are always human-gated.

### A.20.3 Human override at any point

At any point in a flow, a human can stop the run, correct course, and resume. The system should never be in a state where the only way forward is "trust the AI." Specific overrides:

- Pause any running flow immediately
- Reject and provide feedback on any artifact
- Prune entire subtrees that shouldn't exist (A.21.4)
- Force restart stuck nodes
- Manually kick off sub-runs to fix upstream issues

### A.20.4 Dry-run mode

Structural estimation of a flow without making LLM calls or committing anything. Given a flow type and input, the system computes: the shape of the work (which components would be visited, in what order), the number of LLM calls required, the estimated token budget based on configured defaults for context sizes, and which nodes would be created or regenerated. No LLM calls are made — the estimation uses configured defaults. This lets teams evaluate scope and cost before committing budget, and is also useful for testing bundle and configuration changes.

### A.20.5 Diff-first review

The review UI defaults to **diff view**, not full document view. No reviewer should be presented with a 20,000-word document and asked "is this good?" — they see what changed since the last version. Full document view is available but is not the default.

The diff view supports multiple baselines:

- **Diff since last version** — the default. Shows what changed in the most recent generation/revision.
- **Diff since last view** — accumulated changes since the current user last viewed this artifact. If a reviewer misses two review cycles, they see the total change across both, not just the latest. Per-user view tracking makes this possible.
- **Diff since event** — changes since a specific event (a particular approval, a flow run completion, a point in time). The user selects the baseline from the event log or version history. This is essential for catching up after an absence or auditing what changed during a specific flow.

This applies to both model-artifact review and code review UIs.

### A.20.6 Provenance chain

Any artifact is traceable back through its full generation chain: this code was generated from this plan, which was generated from this component arch doc, which was approved by Alice on March 3rd with these review comments, which was produced by this flow run, triggered by this feature request, which was proposed by David in response to this chat conversation. The provenance chain is surfaced in the UI — clicking any artifact opens a panel showing its lineage. This is derived from the event log and the structural edges, and it is one of the single most reassuring capabilities for teams auditing an AI-driven workflow.

### A.20.7 Rollback

Reversion to any previous project state is a single action. The event-sourced model makes this possible — rollback appends new events that undo the delta from the target state to the current state, never destroying history. Subtree rollback is supported: revert a node to version N, and the system automatically reverts each descendant to the version it was at immediately after the ancestor reached version N. This uses the event timeline to find the contemporaneous version of each child, so the user picks one point in the ancestor's history and the entire subtree snaps to its state at that moment. This avoids manually reverting descendants one by one and guessing which version corresponds to the ancestor's state.

### A.20.8 Self-hosted deployment

The entire stack (Catapult, PostgreSQL, the code repository host if used) runs on the customer's infrastructure. No data leaves their network. Combined with BYO LLM credentials (A.12), customers control every external dependency — the LLM traffic goes directly from the sandbox to the provider, not through a Catapult-operated proxy. This is essential for teams with security or compliance requirements.

### A.20.9 Cost visibility

Token tracking (A.12.3) is surfaced in the UI at multiple levels: per node, per flow run, per project. Aggregate displays show "this run used X tokens across Y calls, across these models" so teams can understand and predict their API spend. Runaway prompt growth is visible the moment it happens at the node or tier level — a fragment whose regen suddenly costs 5× what it did yesterday surfaces immediately in the review panel, not later in a log.



## A.21 Operational invariants

These requirements are derived from edge cases, bugs, and hard-won knowledge from Siege Engine's production use. They are non-negotiable.

### A.21.1 Dependency satisfaction

Dependencies are satisfied when a parent artifact has been **generated** (status in `approved`, `awaiting_review`, or `stale`), not only when approved. This allows downstream generation to proceed while upstream is still under human review. Without this, a single slow reviewer blocks the entire pipeline.

### A.21.2 Fan-out always pauses for review

Fan-out stages — the steps that create or modify the component tree structure — must always pause for human review regardless of auto-approval settings. Structural changes are too consequential to auto-approve. This is a hard override on the auto-approval system, not a configurable behavior. See also A.3.4.

### A.21.3 Blocking PR rule

If any outstanding PRs exist for a project from a prior flow run, new flows cannot start. All PRs from the prior run (at whatever granularity level the project is configured to) must be merged or closed before a new flow begins. This prevents the model from drifting out of sync with the codebase. Merge order follows the branch hierarchy (A.10.5). Sub-runs are exempt — they contribute to their parent flow's branch hierarchy and exist precisely to handle mid-flow corrections.

### A.21.4 Debugging and administrative tools

The system provides a set of administrative actions and debugging screens, separate from the normal review workflow.

**Administrative actions** (available to admins — gated on the `admin.*` atom family):

- **Prune** — Remove a node and its entire downstream cascade from the model. For example, a fan-out produced a component that shouldn't exist. Unlike reject (which regenerates), prune deletes. Emits appropriate events for the removal.
- **Force restart** — Force a stuck or failed node back to pending and re-execute, bypassing normal status transition rules.
- **Reset all** — Reset every node in the current run back to pending, clearing all generated state.
- **Force sync / repair** — Rebuild the materialized projection from the event log. Detects and resolves orphaned executions, zombie runs, and stale state.

**Debugging screens** (per project):

- **Snapshot viewer** — the current materialized projection in full, showing the authoritative state of all nodes, runs, and artifacts.
- **Event log** — the last N events (filterable, pageable), showing what happened and in what order.
- **Frontend log** — client-side log capturing UI errors, WebSocket connection state, and user actions.
- **Error panel** — aggregated errors from both frontend and backend for the current project, with timestamps, stack traces, and source labels.

**Error handling UX** (for all users, not just admins). When a node fails, the failure is surfaced inline in the DAG visualization and the review UI — not just a "failed" badge, but the reason: the raw LLM output that failed to parse, the CI error log, the Git error, the timeout details. Users need enough context to decide whether to retry, leave feedback, or escalate to an admin. Notifications for failures follow the same routing as review notifications (to the component owner).

### A.21.5 Cascading readiness re-scan

After the scheduler enqueues or completes any job, it must re-scan all candidate work for newly unblocked tasks — not just the directly affected node. Completing component A's architecture might unblock component B (which depends on A via the dep graph), and B may have already been passed in a linear scan. The scheduler's query pass must loop until no more work is found in a single iteration. This falls out naturally from the state-driven scheduling model (A.3.2) — the scheduler's queries re-run on every reducer commit and every sweeper tick, so missed unblockings are eventually picked up regardless.

### A.21.6 Centralized run completion

Run completion — transitioning a flow run to terminal status — must happen through exactly one codepath. Siege Engine v1 had bugs where run completion logic was scattered across multiple callers, causing zombie runs that stayed in `running` status indefinitely. The single completion point lives in the flow-run supervisor module and is called from the supervisor's terminal-state handler. Handlers and the scheduler never transition flow-run state directly.

### A.21.7 CI integration

CI is an external system that validates generated code. The integration model:

- **Configuration** — CI is configured on the target repository as part of the foundation component's code-generation responsibility. Catapult does not manage CI configuration directly — the foundation's code generation produces CI pipeline files as it would any other infrastructure file.
- **Status monitoring** — Catapult monitors PR check status via git-host webhooks. When CI completes (pass or fail), the host emits a webhook that Catapult processes.
- **Failure retry** — CI failure triggers a regeneration cycle: the error output is included as additional context in the next code-generation attempt. The number of CI retry cycles is configurable per project, with a default limit. After exhausting retries, the node is marked `failed` and the failure surfaces in the review UI with the full error context.
- **Optional** — projects without CI skip the CI loop entirely. The flow proceeds directly from AI code review to human review.

### A.21.8 Phase boundary checks before execution

Stop-point checks (tier boundaries, user-configured pause points) must be evaluated **before** entering a stage's execution, not after. The check acts as a gate: stages past the stop point are never entered. Checking after execution means boundary-crossing stages run before the pause is detected.

### A.21.9 Cross-run execution deduplication

Before creating a new execution for a node, check for existing `running` executions for the same node **across all runs**, not just the current run. Scoping this check to a single run allows duplicate executions when sub-runs or manual triggers overlap. Deduplication at enqueue time (on `(job_type, payload)`) is the first line of defense; the cross-run check is the safety net.

### A.21.10 Retries are sub-runs

Failed executions are not retried in-place. A retry is a sub-run: it pauses the current run, creates a new run scoped to the failed node, executes, and returns control to the parent. This keeps the execution model uniform — there is no special "retry" concept, just the same sub-run machinery used everywhere else. The original failed execution remains in its terminal state in the event log.

### A.21.11 Reconciliation on startup

On server startup, the system must reconcile all projects: rebuild materialized projections from the event log (the event log is always the source of truth), detect and resolve orphaned executions (`running` with no active job → mark `failed`), complete zombie runs (`running` with no active executions → mark `failed`), and cancel stale queued jobs. This is a first-class recovery mechanism, not an afterthought.

**Graceful shutdown.** On planned shutdown (deploys, upgrades), the system drains active work: stop accepting new node executions, let active LLM calls complete within a configurable grace period (default 10 minutes — AI coding assistant runs can take this long), then shut down. If a node doesn't finish within the grace period, it gets killed and reconciliation on the next startup marks it `failed` — the same path as a crash, retryable like any other failure. Draining is simple and predictable; checkpointing mid-LLM-call is not practical because partial responses are meaningless. With conservative concurrency defaults, drain typically waits on 1-3 active calls.

### A.21.12 LLM output parsing resilience

LLM output format is unreliable. All structured output extraction — parseable fragments, feature lists, requirement entries, policy blocks, plan bodies, code file lists — must use multiple parsing strategies with fallbacks. Try strict parsing first, fall back to regex extraction, then to smaller-model re-extraction if configured. Never fail a stage because the LLM returned valid content in an unexpected format. Persistent parse failure after all strategies exhausted escalates to human review with the last failed output and the parse errors visible.

### A.21.13 LLM concurrency limits

Parallel execution within a flow must respect a configurable concurrency limit for LLM calls. Siege Engine v1 hardcoded this to 1 after higher values caused resource exhaustion and rate-limiting cascades. The limit should be configurable per project but default to conservative values (e.g., 2-4 concurrent calls). Exponential backoff on rate-limit errors — typically 3 attempts with 1-second base delay, doubling — and no retries on quota-exhaustion errors (those need human intervention to resolve).

---



---

# Part B — Architecture

## B.1 Elixir / OTP

The application is built in Elixir on the BEAM VM. OTP provides the concurrency primitives, supervision trees, and fault tolerance model that underpin flow execution, real-time updates, process management, and the state-driven scheduler. Supervision trees give us crash-isolation by design: a failed flow run doesn't take down the review UI, a crashed LLM call doesn't take down the reducer, and reconciliation on startup (A.21.11) rebuilds state from the event log regardless of how the system came down.

The BEAM's soft-realtime scheduling is a good fit for a workload dominated by I/O-bound LLM calls and UI push notifications — many concurrent lightweight processes each handling one in-flight request without the thread-per-connection cost.

## B.2 PostgreSQL

Primary data store for all persistent state: the event log (`graph_events`), projection tables (nodes, edges, fragments, drafts, change plans, policies), users, credentials, bundle configuration, per-project overrides, auth audit log, review history, and token usage telemetry.

No second data store for any of this — PostgreSQL is the single operational store. Vector embeddings live in the same database via pgvector (B.5), so there is no separate vector service to operate, monitor, or keep in sync with the primary store.

**Migrations are forward-only.** Downgrade raises. Schema changes land with explicit migrations; the migration history is the audit trail for "when did this column / this edge type / this fragment kind enter the system." Multi-column constraints that SQLite can't represent but Postgres can (partial unique indexes, check constraints with subqueries) are used where they encode real invariants.

## B.3 Commanded (CQRS/ES) and the scheduler

The core domain uses Commanded for command/query responsibility segregation and event sourcing. All state changes to the structured model are expressed as commands that produce events. Events are the source of truth; materialized read models are derived projections; rebuilding from zero must match incremental apply byte-for-byte.

What Commanded gives us for free:

- Complete audit trail of every action as the event log.
- Time travel and revert by replaying events to a prior offset.
- Resumability: a partially-completed flow picks up where it left off when the process restarts.
- Clean separation between "what happened" and "what the current state looks like" — the two are never allowed to drift, because the second is a deterministic function of the first.

Commanded's **aggregates** enforce per-project invariants: pessimistic locking (A.7), status transitions (A.5.5), destructive-operation gating (A.3.3), and the subcomponent depth cap (A.1.7).

### B.3.1 State-driven scheduler module

**The scheduler is a first-class module, not an accidental consequence of Commanded's process managers.** This section specifies it explicitly because it is the most load-bearing deviation from standard CQRS/ES patterns in the system.

Commanded ships with **process managers** — stateful subscribers that react to events and emit commands. Process managers are event-triggered: when an event arrives, the process manager updates its internal state and possibly issues a command. For many workflows this is the right shape, but it is not what the scheduler wants. The scheduler wants to react to *state*, not to *events*: "whenever the current projection satisfies condition X, enqueue job Y." This is closer to a reactive materialized view than to a stateful process manager.

The scheduler module:

- **Subscribes to reducer commits via `Phoenix.PubSub`.** The reducer broadcasts a commit notification on a per-project topic after every successful `append_event` transaction; the scheduler is a subscriber to every project's topic. Every message triggers the fast path: the scheduler re-runs its "what's ready?" queries against the current projection for that project and enqueues any jobs the queries identify as missing. Phoenix.PubSub is a good fit because it is topic-based, fire-and-forget, in-process in single-node deployments, and automatically distributed across a BEAM cluster in multi-node deployments — the same code path handles both.
- **Runs a sweeper loop** on a configurable floor interval (default 30-60 seconds) as the consistency guarantee. The sweeper runs the same queries the fast path runs, catching anything the fast path missed due to subscriber restart, dropped signals, or transient races between the commit and the subscriber. The sweeper is also the mechanism that picks up any missed work on process restart — reconciliation (A.21.11) rebuilds projections from the event log, and then the first sweeper tick enqueues any regens that the reconciled state implies.
- **Is stateless.** The scheduler holds no in-memory coordination state; its inputs are the projection and the current set of Oban jobs, and its output is a set of `Oban.insert` calls. Multiple scheduler processes — on the same node, on different nodes of a cluster, whatever — can run concurrently without coordinating, because duplicate enqueues are rejected at the Oban insert layer (B.4).
- **Queries are data, not code** (A.11). The rules the scheduler enforces are loaded from the bundle configuration, so adding a new regen trigger is a configuration change, not a scheduler module change.
- **Is the only path into the job queue.** No other handler calls `Oban.insert` or equivalent. Mint handlers, regen handlers, approval handlers, deferred feedback handlers, and every other state-modifying path commits events and exits; the scheduler reads the new state and decides what runs next.

**Why not process managers.** Commanded's process managers could be used to implement the fast path, but they don't fit the two other properties the scheduler wants: a state-polling sweeper that runs regardless of events, and stateless concurrency-safe re-entry. Process managers are stateful by design and their coordination story is "one process per in-flight workflow," which is a different mental model from "one set of queries over current state." Splitting the scheduler across two idioms — process managers for the fast path, a polling loop for the sweeper — would make the "what runs next" logic live in two places with different debugging surfaces. Phoenix.PubSub + Oban's unique-job constraint lets the scheduler be a single module with two trigger paths into the same query rules.

**Implications for the event stream.** Because handlers don't emit "next job" messages, the event stream is cleaner: every event is a real state change, not a workflow coordination signal. The event stream is the history of the project, not a bus for handler-to-handler messaging.

## B.4 Oban

Background job processing for side-effectful operations that don't fit Commanded's event-driven model: LLM API calls, git operations against the code repository, CI polling, credential refresh, and anything else that needs retries, scheduling, and observability. Oban jobs are enqueued by the scheduler (B.3.1) and, on completion, emit events via Commanded commands back into the domain layer.

Oban sits underneath the scheduler in the architecture stack: the scheduler decides *what* to enqueue, Oban handles *how* to run it reliably — retries on transient failures, exponential backoff on rate limits, scheduled retries on rate-limit exhaustion, concurrency limits per queue.

**Unique-job enforcement is load-bearing.** Every job the scheduler enqueues carries a uniqueness constraint (Oban's `unique` option) scoped to `(worker, args, queue, states)` — typically matching any job in the `available`, `scheduled`, `executing`, or `retryable` states. Because the scheduler is stateless and runs concurrently across BEAM nodes (B.3.1), it relies on Oban's insert path to reject duplicate jobs via a Postgres unique index rather than on a scheduler-level lock. This is the single mechanism that keeps "two commit signals arriving simultaneously" from producing two copies of the same regen job, and it's the reason the scheduler can be safely restarted, sweeper-polled, and run on every node of a cluster without coordination.

**Queue shape.** One Oban queue per LLM provider (so provider-specific rate limits can be respected independently), one for git operations, one for CI polling, one for general background tasks. The per-queue concurrency is configurable per project with conservative defaults (A.21.13).

**Oban Pro is optional.** The core system depends only on Oban core (Apache 2.0, AGPL-compatible — see B.11). The unique-job constraint described above is available in Oban core via the `unique` keyword on `Oban.Job` — Oban Pro is not required for the scheduler's dedup story. Oban Pro's more advanced features (batch processing, the web dashboard, workflow orchestration primitives) are behind an optional module that is not required for core functionality; commercial licensees may use Oban Pro at their discretion.

## B.5 pgvector

Vector embeddings stored in PostgreSQL via pgvector for semantic retrieval during context assembly (A.3.5). Document chunks — fragments, implementation prose, responsibility descriptions, change summaries — are embedded and indexed so that deep nodes can retrieve relevant ancestor context by semantic similarity rather than consuming entire documents. The retrieval strategy varies by flow and tier.

Embedding writes are triggered by fragment / node updates via the scheduler's query layer: "for every node or fragment whose content has changed since its last embedding, enqueue a re-embed job." Embedding is a background operation; it does not block the generation path.

Vector search also powers parts of the David chat interface (A.19) when David needs to find relevant nodes for a question that isn't anchored to a specific artifact.

## B.6 Git backend for code shipping

Every Catapult instance includes a **bundled gitea sidecar** that is the authoritative local git substrate (A.10.1). Gitea holds every project's code repository, every flow run's branch hierarchy, every approved leaf commit, and every imported bundle in the instance bundle library (A.11.5). External git hosts (GitHub, GitLab, other gitea instances, etc.) are reached only through the **forge adapter plugin layer** (A.10.2), which pushes approved branches and creates PRs on the external forge but does not touch local repository state. The git backend is **not** used to store or version design artifacts; the event log plus projections are the authoritative store for all model state (A.9).

The local gitea substrate's role:

- **Branch creation** for flow runs (run branch, per-component branches, per-subcomponent branches — see A.10.5). All branch operations land in local gitea first.
- **Commit composition** for leaf-level code changes. Each impl leaf produces one commit per flow run, scoped to the leaf's territory. Commits are authored directly via gitea's HTTP API; no git CLI subprocess lives anywhere in the hot path.
- **PR lifecycle** on local branches — creation, review comments, merge operations. Projects with no forge adapter configured review and merge entirely against local gitea; projects with an adapter mirror branches and PRs to the external forge via `push_branch` / `create_pr`.
- **Bundle storage** — the instance's bundle library is a gitea namespace (`bundles/*`), with each entry a mirror of the bundle author's upstream. Bundle import, approval, version pinning, and airgapped operation all reuse the same substrate.
- **Thread-safe concurrent access.** Gitea's API is thread-safe by design, avoiding the git CLI's concurrency problems and the immaturity of native Elixir git libraries.

The external forge plugin layer's role (when configured):

- **`push_branch`** — mirror a branch from local gitea to the external forge after leaf commits are approved.
- **`create_pr`** / **`update_pr`** — lifecycle management of pull requests on the external forge.
- **`read_webhooks`** — consume inbound webhook events (merge, close, review-requested, check-failed) and translate them into catapult-shaped state-change events.
- **`delete_branch`** — clean up branches after merges.

Bundled adapters for MVP: **gitea** (trivial, identity-ish since the substrate is gitea) and **GitHub**. New adapters are ~200 lines of Elixir against a fixed contract and do not reach into local repository state.

**For design-only projects**, the code-shipping layer is inert — the local gitea still runs (because bundle storage uses it), but no code repository is registered under the project's name and the code-generation tiers never fire. The entire value proposition for design-only projects is the structured-model review loop.

Avoiding a git mirror for documents is one of the largest simplifications relative to catapult v1: no "git commit at review boundary" concept, no run-branch hierarchy for docs, no two-store reconciliation problem, no "what happens if the git commit succeeds and the DB commit fails" failure mode for design state. The event log is the history; git is for code and bundle storage.

## B.7 Phoenix / LiveView

Web framework and real-time UI layer. Phoenix Channels provide WebSocket-based live updates for every client subscribed to a project. LiveView powers the interactive DAG visualizations, artifact viewers, review interfaces, the lobby, change-plan review panels, and David's chat UI. No separate frontend build — the UI is server-rendered with client-side interactivity via LiveView's DOM-patching protocol.

LiveView's process-per-session model fits the real-time update story cleanly: each connected user has one process, that process subscribes to the project's reducer-commit stream, and DOM updates are pushed to the client as state changes. A user viewing a component's review page sees the review-queue counter tick down, the artifact's status transition, and other users' comments appear in-place, without an explicit refresh.

**Where LiveView is not enough.** The Cytoscape-based decomposition graph and the structured drag-drop UIs (feature → responsibility mapping, responsibility → component mapping, subresp → subcomponent mapping, dependency editor, domain-parent editor) use JavaScript components hosted inside LiveView via its JS interop layer. LiveView handles server-authored state; the JS layer handles the graph interaction. Operations the user takes in the graph editor produce prose instructions (A.1.1) that flow back through the regen pipeline — the JS layer does not mutate state directly.

## B.8 AI coding assistant adapter

Leaf-level code generation is delegated to AI coding assistants via an adapter interface (A.17). The adapter abstracts over the specific assistant — Claude Code, Cursor, Aider, or a future alternative — so the core pipeline stays decoupled from any one vendor. Adapters implement a common contract: given a plan node, a territory, and the current repository state, produce a code diff that realizes the plan.

The adapter runs inside the AI sandbox (A.18): filesystem access scoped to the territory, no arbitrary network, no credential access, bounded resource limits, template isolation. The orchestrator injects LLM credentials into the assistant invocation at call time; the assistant never sees the credential store directly.

**Multiple adapters can coexist** per project: a project could use Claude Code for complex refactor tasks and a cheaper/simpler adapter for well-defined plan executions. Per-tier configuration (A.11) controls which adapter runs for which node kind.

## B.9 LLM integration

- **BYO credentials** — customers supply their own API keys, stored encrypted per user/project/instance (A.12).
- **Multiple providers supported** behind a common interface. The system ships with adapters for the major providers; adding a new provider is an adapter module plus a credential-scheme entry.
- **Model and temperature** are configurable at the project, tier, and node-override levels (A.11.3).
- **Token tracking** per call with model identifier recorded alongside token counts (A.12.3). Synchronous with the generating job handler. Missing telemetry is treated as a generation failure for alerting purposes.
- **Exponential backoff on rate-limit errors**: 3 attempts with a 1-second base delay, doubling. Quota-exhaustion errors do not retry; they escalate to the review UI with the error context visible so the user can either provide different credentials or wait.
- **Adapter-level prompt injection defenses**: the adapter rejects system-prompt manipulation attempts from within user-supplied context (for example, text that tries to override the template's output format instructions). This is layered on top of template isolation in the sandbox (A.18).

## B.10 Observability

System-level monitoring and observability for operating Catapult in production:

- **Metrics** — Prometheus-compatible metrics: request latency, LLM call success/failure rates, LLM call duration, queue depths, active flow runs per project, git operation latency, database connection pool utilization, vector embedding query performance, scheduler query latency, sweeper iteration latency.
- **Structured logging** — all log output is structured (JSON) with correlation IDs that trace a request through the full pipeline: Commanded command → event → scheduler query → Oban job → LLM call → git operation → reducer commit. This enables tracing a single node execution across every system component.
- **Health checks** — liveness and readiness endpoints for the Catapult service, the database, the git backend, and the LLM provider health as reflected in recent success rates. Suitable for orchestrator probes and uptime monitoring.
- **Scheduler introspection** — admin-visible view of the scheduler's current query results: for each query rule, what rows match right now, which of those already have queued or running jobs, and which would be enqueued on the next scheduler pass. This is the primary debugging surface for "why isn't my flow running?" questions.
- **Error panel** per project (A.21.4) — aggregated errors from both frontend and backend with timestamps, stack traces, and source labels.

## B.11 Licensing model

Catapult uses a **dual-license model**:

- **AGPL v3** for the public open-source release. Anyone can use, modify, and deploy Catapult freely. Modifications to the core must be published if the modified version is offered as a network service. This closes the SaaS loophole that plain GPL leaves open — cloud providers cannot run a modified Catapult as a managed service without contributing back.
- **Commercial license** available for organizations whose legal or compliance requirements are incompatible with AGPL. The commercial license permits proprietary modifications, private deployment without source disclosure, and use of proprietary optional dependencies.

**Architectural implications for dual licensing:**

- The core system (pipeline engine, event sourcing, scheduler, reducer, review workflow, LiveView UI, structured-model projections) is AGPL and must not depend on any proprietary libraries.
- **Oban**: the core depends only on Oban core (Apache 2.0, AGPL-compatible). Oban Pro features (unique jobs, batch processing, web dashboard) are behind an optional module that is not required for core functionality. Commercial licensees may use Oban Pro at their discretion.
- **Git backend sidecar**: Gitea is AGPL-compatible and communicates over HTTP — a separate process, not a derivative work. No licensing conflict.
- **Plugin / extension boundary**: third-party tools communicating with Catapult over HTTP/API are not derivative works. Plugins loaded into the Elixir runtime are derivative works under AGPL. This boundary must be documented clearly for integrators.
- **Contributor License Agreement (CLA)**: required for contributions to the core repository, granting the project the right to distribute contributions under both AGPL and commercial licenses.

Self-hosted AGPL deployments satisfy the entire feature set described in this document without any commercial components. The commercial license is an option for organizations that cannot use AGPL code, not a gate on functionality.

