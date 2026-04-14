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

**Trigger mechanism.** The scheduler re-runs its queries on two paths. The **fast path** is a pub-sub signal: after every successful reducer commit, a notification is broadcast in-process and the scheduler picks it up and re-runs its queries within milliseconds. The **slow path** is a sweeper that runs on a floor interval (configurable, default 30-60 seconds) and executes the same queries unconditionally, catching anything the fast path missed due to subscriber restart, signal loss, or race conditions. The fast path is the latency ceiling; the sweeper is the consistency floor.

**Concurrency.** The scheduler holds a project-scoped lock while running its queries, so two simultaneous commit signals don't produce duplicate enqueues. Jobs themselves are deduplicated on `(job_type, payload)` at enqueue time, so even if the lock fails for some reason, duplicate-job prevention is layered.

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

- `expansion_*` — feature expansion. Reviewed once, mints `feat_*`. Singleton per project.
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

Catapult generates code as a final leaf pass (A.3.1 step 11) and the generated code ships via git commits against a target repository. For the MVP, all leaves within a project target a single repository (monorepo assumption), and the `{repository, folder}` territory mapping (A.1.11) defines which leaf owns which folder. Multi-repo is a post-MVP extension; the data model supports it but the flow orchestration and PR composition assume one repo.

### A.10.1 One commit per leaf

Each `impl_*` leaf produces a single commit per flow run. The commit is scoped to the leaf's territory (folder) and contains only files that belong to that leaf. Cross-leaf changes — files that touch two territories — are a manifest-level error surfaced in the admin tools, because the territory rule is what keeps generation parallelizable and leaf-scoped.

### A.10.2 Configurable PR granularity

PR granularity is configurable per project to one of three levels: **system**, **component**, or **subcomponent**.

- **System level** (default) — One PR for the entire flow run. All leaf commits compose into a single PR against main.
- **Component level** — One PR per component. Each component's leaf commits compose into a PR against the run branch.
- **Subcomponent level** — One PR per subcomponent. Each subcomponent's leaf commits compose into a PR against the component branch.

### A.10.3 Branch hierarchy

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

Code PRs are created at whichever level the project's PR granularity is configured to. Review flows upward through the branch hierarchy: subcomponent branches merge into component branches, component branches merge into the run branch, and the run branch merges into main. Catapult controls the review order and communicates which branches are ready in what sequence.

### A.10.4 Blocking PR rule

If any outstanding PRs exist for a project from a prior flow run, new flows cannot start. All PRs from the prior run must be merged or closed before a new flow begins. This prevents the model from drifting out of sync with the codebase. Sub-runs are exempt from this rule — they contribute to their parent flow's branch hierarchy and exist precisely to handle mid-flow corrections.

### A.10.5 Git is only for code, not for design

A project without code generation (design-only projects, hypothetical-future-project explorations, documentation-only workloads) does not need a git repository at all. The structured model is the entire artifact. The git layer is optional per project — enable it when you want code shipping, skip it otherwise.

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
