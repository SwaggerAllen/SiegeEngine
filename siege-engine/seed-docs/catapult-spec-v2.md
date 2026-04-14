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

## A.2 Flows

*(to be filled in)*

## A.3 Phases and generation order

*(to be filled in)*

## A.4 Projection sources, bootstrap nodes, and change plans

*(to be filled in)*

## A.5 Review and approval

*(to be filled in)*

## A.6 Flow lobby

*(to be filled in)*

## A.7 Concurrency and locking

*(to be filled in)*

## A.8 Resumability and recoverability

*(to be filled in)*

## A.9 Document storage model

*(to be filled in)*

## A.10 Git for code shipping

*(to be filled in)*

## A.11 Prompt and DAG configuration

*(to be filled in)*

## A.12 Credentials and token tracking

*(to be filled in)*

## A.13 Real-time updates and external integration

*(to be filled in)*

## A.14 Authentication and authorization

*(to be filled in)*

## A.15 Multi-project support

*(to be filled in)*

## A.16 Bootstrap flow

*(to be filled in)*

## A.17 AI coding assistant integration

*(to be filled in)*

## A.18 AI sandboxing

*(to be filled in)*

## A.19 AI chat interface — David

*(to be filled in)*

## A.20 Adoption and trust

*(to be filled in)*

## A.21 Operational invariants

*(to be filled in)*

---

# Part B — Architecture

*(to be filled in)*
