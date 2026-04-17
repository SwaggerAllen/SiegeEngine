# SiegeEngine v2 — Product Roadmap

Checkbox-driven roadmap from the event-sourced foundation through a
shippable MVP. Each phase is a vertical slice that lands behind an
approval gate and is demoable end-to-end before the next phase starts.

Authoritative scope: `docs/architecture/v2-rearchitecture.md` §MVP scope.
That doc is the "what" — this file is the "how, in what order, and
where are we."

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 0 — Foundation (data layer)

Landed on `main` as PR #290. Everything v2 writes goes through this.

- [x] Event log table + append-only writer (`GraphEvent`)
- [x] Reducer with one branch per event type (`backend/graph/reducer.py`)
- [x] Projections: `Node`, `Edge`, `Fragment`, `Draft`
- [x] Rebuild-from-log correctness test (incremental == replay)
- [x] Instruction vocabulary Pydantic models
- [x] Pending-change queue + `v2.apply_instructions` stub handler
- [x] Pipeline job queue with handler registry
- [x] Crockford base32 ID minting (`backend/graph/ids.py`)
- [x] Debug projection endpoint (`GET /api/projects/{id}/model`)
- [x] Alembic baseline migration `b1_v2_foundation`

## Phase 1 — Feature expansion (first vertical slice)

Landed on `claude/layered-dag-algorithms-llp3t`. Proves the foundation
holds end-to-end: events → reducer → projections → queue → handler →
routes → UI, with only the three new ingredients (LLM call site, one
prompt template, minimal approval UI).

- [x] `expansion` tier + migration `b2_expansion_tier`
- [x] `backend.graph.expansion` bootstrap/lookup helpers
- [x] `backend.graph.prompts.feature_expansion` prompt
- [x] `v2.generate_feature_expansion` job handler (regen discards prior pending)
- [x] `bootstrap + enqueue` on project creation
- [x] Four HTTP routes (`get / feedback / approve / discard`)
- [x] FastAPI lifespan wires the pipeline worker loop
- [x] React Query hooks + `FeatureExpansionPanel` with four visual states
- [x] Backend mypy clean, 149 v2 tests green, 7 component tests green
- [ ] **Generation telemetry plumbed from first real LLM call.** Wrap the LLM client so every call records `(node_id, fragment_or_section, model, prompt_tokens, completion_tokens, timestamp)` to a side table. Surface in the UI on every node that has ever been generated: latest token count shown in-place, not behind a button. Cheap to add now, expensive to retrofit.

---

## Phase 2 — Feature minting from approved expansion

Turn the prose feature expansion into structured `feat_*` nodes.
Features are user intent, not architecture — they fall out of the
expansion naturally as a bulleted list, and the feature list is a
user-facing artifact independent of components.

After approval the expansion node becomes read-only; all ongoing
feature-layer work happens as add/delete/edit on individual
`feat_*` nodes, not by re-editing the expansion. This is the
"approve to mint, then edit children directly" pattern that the
other bootstrap nodes (`reqs_*`, `sysarch_*`) reuse.

- [ ] Prompt: parse approved expansion markdown → list of features (name + one-line intent)
- [ ] Generate-parse validation loop (retry on parse failure, escalate after N)
- [ ] On `DraftApproved` for the expansion node: enqueue `v2.mint_features` job
- [ ] Mint `feat_*` nodes from the parsed list; cascade becomes the destructive-gate moment for the feature layer
- [ ] Flip the expansion node to a read-only state post-approval (historical bootstrap reference only, not a live editing surface)
- [ ] Routes: `GET /{project_id}/features`
- [ ] UI: feature list view on the dashboard under the (now read-only) expansion
- [ ] UI: add/delete/edit actions on individual `feat_*` nodes once minted, feeding the pending-change queue

## Phase 3 — Cold-start resolver chain (reqs, sysarch, subreqs)

The three-stage cold-start chain. Each stage is a bootstrap node
with its own handler, its own approval flow, and its own
read-only-after-approval lifecycle. Implemented as one roadmap
phase because the three handlers share most of their
infrastructure (all reuse the expansion draft → feedback →
approve → mint flow from Phase 1), even though they are wholly
separate nodes in the model.

- **`reqs_*`** — features → top-level responsibilities. Local
  reasoning, low cross-talk. Singleton per project. Approval mints
  top-level `resp_*` nodes and freezes the `reqs_*` node to
  read-only.
- **`sysarch_*`** — top-level responsibilities → components + APIs
  + top-level policies + dep edges + domain-parent edges +
  system-level techspec. Singleton per project. Single
  joint-reasoning call because these are mutually informing.
  Approval mints `comp_*` nodes and edges, top-level `policy_*`
  nodes, **and one `subreqs_*` node per top-level `comp_*`**.
  Freezes the `sysarch_*` node to read-only.
- **`subreqs_*`** — per top-level component, minted at sysarch
  approval. Takes that component's top-level `resp_*` nodes and
  produces the component's subresponsibilities. Same prose-
  iterable shape as `reqs_*` but per-component rather than
  singleton. Approval mints subresp `resp_*` nodes (parented to
  the component) and freezes the `subreqs_*` to read-only. Phase
  4's component-arch pass for a given component cannot run until
  that component's `subreqs_*` is approved.

**Shared infrastructure for the phase:**
- [ ] Alembic migration widening `ck_edges_edge_type` to include `decomposition`. The new edge type is used by both the `reqs_*` mint (`feat_* → resp_*`) and the `subreqs_*` mint (`top_level_resp_* → subresp_*`) below. See architecture doc §Edge type vocabulary for the semantics.
- [ ] `EdgeCreated.edge_type` Literal widened to include `decomposition` in `backend/graph/events.py`. No reducer changes needed — `_apply_edge_created` is generic.
- [ ] Backend `EDGE_TYPES` constant in `backend/models/node.py` widened to match.

**Requirements node:**
- [ ] New singleton `reqs` tier node minted once per project after expansion approval
- [ ] Cold-start vs incremental-add are distinct prompt templates (one job handler picks which)
- [ ] Cold-start prompt: approved feature set → top-level responsibilities. Each `<responsibility>` output carries a `<covers>` child listing the feature IDs it serves (many-to-many, required — see architecture doc §Feature → Responsibility → Component).
- [ ] Incremental-add prompt: existing `reqs` + one new feature → delta
- [ ] Handler reuses the expansion flow (draft → feedback → approve → commit)
- [ ] Generate-parse validation loop (retry-then-escalate). Validator rejects unknown / missing feature IDs in `<covers>` — fed back into the retry loop.
- [ ] On `DraftApproved`: mint top-level `resp_*` nodes **and** `decomposition` `feat_* → resp_*` edges in the same transaction. Flip `reqs_*` to read-only.
- [ ] Routes mirror expansion (`get / feedback / approve / discard`)

**System architecture node:**
- [ ] New singleton `sysarch` tier node minted once the `reqs_*` node is approved
- [ ] Cold-start vs incremental-add prompt templates (one job handler picks which)
- [ ] Cold-start prompt: approved requirements + features → full sysarch (components, APIs, **top-level policies**, dep edges, domain-parent edges, system `techspec`). **The prompt explicitly requires a foundation component** in the component list, whose manifest territory is the project's root folder minus everything the other top-level components claim (see architecture doc §Foundation components).
- [ ] Incremental-add prompt: existing `sysarch` + one new responsibility or feature → delta (re-running policy application for affected components only)
- [ ] Parseable output sections **in order**: system `techspec`, per-component (API intent, responsibilities covered), `<policies>` (top-level policy list referencing `resp_*` by ID in `required`), `<dependencies>` (dep edge list — including **role-level speculative policy-induced edges**), `<domain-parent>` (domain-parent edge list). Policies precede dependencies so policy-induced dep edges land in the same pass at the fidelity the sysarch's role-level per-component summaries support.
- [ ] Generate-parse validation loop (retry-then-escalate) — sysarch output is load-bearing for everything downstream
- [ ] Handler reuses the expansion flow (draft → feedback → approve → commit)
- [ ] On `DraftApproved` for the sysarch node: parse structured output and emit:
  - [ ] `NodeCreated` for each new `comp_*` (with API intent stored as the `pubapi` fragment and techspec as `techspec` fragment)
  - [ ] `NodeCreated` for each new `policy_*` (projected from the `<policies>` fragment, referencing `resp_*` for `required`)
  - [ ] `EdgeCreated` for each `dependency` edge (including speculative policy-induced ones)
  - [ ] `EdgeCreated` for each `domain_parent` edge
  - [ ] Diff against existing comp / edges — preserve lineage, mark orphans
  - [ ] **No `policy_application` edges yet.** Top-level policy application is deferred to component-arch time (see Phase 4) — the per-component summaries sysarch has available aren't detailed enough to make application decisions confidently, and forcing application here would either produce wrong edges or push implementation detail into sysarch summaries that we're trying to keep at role-level.
- [ ] Cycle prevention on dependency edges (DFS from target to source) inside the parser — reject the whole parse on a cycle and loop back to regen with the error
- [ ] Initial mint is treated as destructive at the child level (gated on explicit approval)
- [ ] Flip `sysarch_*` to read-only post-approval
- [ ] **On `DraftApproved` for the sysarch node, also mint one `subreqs_*` node per top-level `comp_*`** (parent_id = the component). The subreqs handler's bootstrap is the same pattern the expansion handler uses at project creation — mint the node and enqueue its initial generation job.
- [ ] Routes mirror expansion
- [ ] UI: read-only requirements and system architecture views with the expansion-style four-state panel each

**Subrequirements node (per top-level component):**
- [ ] New `subreqs` tier node kind minted at sysarch approval, one per top-level `comp_*`. Not a singleton — use the full Crockford suffix. Parent is the owning component.
- [ ] Cold-start vs incremental-add prompt templates (one job handler picks which)
- [ ] Cold-start prompt: the owning component's sysarch entry (role + API intent) + its assigned top-level `resp_*` nodes → that component's subresponsibilities as prose. Each `<subresponsibility>` output carries a `<derived-from>` child listing the top-level resp IDs it decomposes (many-to-many, required).
- [ ] Incremental-add prompt: existing `subreqs_*` for this component + one new top-level `resp_*` (e.g. because the sysarch got regenerated and assigned a new top-level resp to this component) → delta
- [ ] Handler reuses the expansion flow (draft → feedback → approve → commit)
- [ ] Generate-parse validation loop (retry-then-escalate). Validator rejects `<derived-from>` references to top-level resps that aren't assigned to the owning component — leak across component boundaries is a parse error fed into the retry loop.
- [ ] On `DraftApproved`: parse the prose into structured subresp entries and emit `NodeCreated` for each subresp `resp_*` (parented to the owning component) **plus** `decomposition` `top_level_resp_* → subresp_*` edges in the same transaction. Flip the `subreqs_*` to read-only. Enqueue this component's component-arch generation job, which blocks on subreqs approval.
- [ ] Routes mirror expansion, scoped by owning component ID: `get / feedback / approve / discard` for each component's subreqs
- [ ] UI: read-only subrequirements view per top-level component, with the expansion-style four-state panel
- [ ] Diff against existing subresps on re-approval: preserve lineage, mark orphans

**Structured edit UIs for feat↔resp, resp↔comp, and dependency / domain-parent edges are NOT part of this phase.** They're layered on top of the minted structure in Phase 11 — every structured UI is a prose-instruction generator feeding the pending-change queue, not a separate generation step.

## Phase 4 — Component architecture docs (parseable)

The biggest single chunk. This is where fragments and section-aware
propagation start paying off, and this is also where the shared
diff-aware regen helper lands — built as a primitive from the start,
not retrofitted later. This is **also** where policies become real
for the first time: component-local policy minting, plus the
application pass for **both top-level and component-local policies**,
all live here rather than in Phase 3. Top-level policies are minted
by Phase 3 but deliberately have no application edges until this
phase runs and a component-arch regen resolves them against the
now-detailed component description.

- [ ] **Blocks on `subreqs_*` approval for this component.** Component-arch generation cannot start until the owning `subreqs_*` is approved and its subresp `resp_*` nodes are minted. The job handler checks this and no-ops (or re-queues with delay) until the precondition holds.
- [ ] XML section parser for the five required sections in order: `<technical-specification>`, `<public-surface>`, `<private-surface>`, `<policies>`, `<dependencies>`
- [ ] Generate-parse validation loop with retry-then-escalate
- [ ] Fragment extraction: on approval, split into `comp_X_techspec`, `comp_X_pubapi`, `comp_X_privapi`, `comp_X_policies`, `comp_X_deps`
- [ ] Fragment kinds validated as single-token at parser boundary
- [ ] `FragmentUpdated` event fires per changed fragment
- [ ] **Shared regen-prompt assembly helper** — one module used by every tier's regen: parent doc + related features + dep `pubapi` fragments + **pre-minted subresponsibilities for this component** (from its approved `subreqs_*`) + **top-level policy candidates** (all top-level `policy_*` nodes, regardless of existing application edges, so the LLM can apply ones that weren't yet resolved against this component) + already-applied policies pulled via existing `policy_application` edges + neighbor diffs. Phases 5/6/7/8 reuse it rather than reimplementing.
- [ ] Fragment-level diff computation (before/after per fragment) lands here, not in a later consolidation phase
- [ ] Component regen prompt in dependency topological order, via the shared helper
- [ ] Prompt input scoping: parent `techspec` + related features + `pubapi` fragments of deps + pre-minted subresps + top-level policy candidates + already-applied policies (NOT full dep docs)
- [ ] **Component arch generation produces `<policies>` before `<dependencies>` in the same LLM call**, so policy-induced dep edges land in `<dependencies>` naturally instead of being backfilled
- [ ] **Foundation subcomponent requirement** — when a component is decomposed into subcomponents, the comparch prompt explicitly requires one of them to be a foundation subcomponent whose manifest territory is the component's root folder minus everything the other subcomponents claim (see architecture doc §Foundation components). Un-fanned-out components do not need a foundation child.
- [ ] Techspec propagates downward only; child impl changes do not regenerate parent techspec
- [ ] **Subresponsibilities are NOT generated here.** The component-arch pass treats its component's subresp `resp_*` nodes as a stable pre-minted input from the `subreqs_*` stage (Phase 3). Comparch output maps subcomponents to those pre-minted subresps, rather than inventing the subresps in the same pass.
- [ ] **Component-local policy minting**: on `DraftApproved`, project each entry in the component's `<policies>` fragment into a `policy_*` node (with `parent_id` = the minting component; `required` = any `resp_*` that exists at generation time, top-level or this component's pre-minted subresps). Deleting an entry removes the policy and cascades to its application edges.
- [ ] **Top-level policy application pass**: on each component arch approval, run an LLM pass over the full set of top-level `policy_*` candidates against **this one component's** techspec + subresponsibilities, emit `policy_application` edges for the applicable ones, and remove existing edges the LLM now says don't apply. This is where "does this top-level policy apply to this component" actually gets decided — not at sysarch approval.
- [ ] **Component-local policy application pass**: same shape, but scoped to the subcomponents the component just minted. Component-local policies only apply within their own subtree.
- [ ] **Patch missing policy-induced dep edges**: if the LLM determines a top-level policy applies to this component and the corresponding dep edge to the policy's `required` component is missing (sysarch's speculative first pass missed it), the component's own `<dependencies>` section adds it. Straightforward `EdgeCreated` on approval.
- [ ] **Incremental re-application** on component-set changes within this subtree: `NodeCreated` with tier `comp` + parent in this subtree, `NodeReparented` into/out of this subtree, merge/split of subcomponents — re-run the application pass for just the affected edges.
- [ ] Structured UI #3: component decomposition graph editor (Cytoscape)
- [ ] Tests: transclusion drift detection (system arch `pubapi` vs component arch `pubapi`), policy minting round-trip, application-edge emission for both top-level and component-local policies, depth-cap reducer rejection when a subcomponent would get a subcomponent child
- [ ] Depth-cap invariant wired into the prompt: "if decomposition needs three levels, stop and recommend promoting the middle layer"

## Phase 5 — Subcomponent architecture docs (leaf tier)

Same shape as Phase 4 but one level below. Per the subcomponent
depth cap, subcomponents are terminal — they have no children of
their own kind, so their arch docs omit the `<policies>` section
(nothing new to target) and don't run an application pass.

- [ ] Subcomponent decomposition prompt and handler — generates the same four sections as component arch (`techspec`, `pubapi`, `privapi`, `deps`) but NOT `<policies>`
- [ ] Subcomponent dependency scoping (same-parent siblings + parent's sibling components only)
- [ ] Structured UI #4: subresponsibility → subcomponent mapping
- [ ] Promotion / demotion instructions work across the two tiers without changing IDs (subcomponent ↔ component)
- [ ] Reducer enforces the depth-cap invariant: any `NodeCreated`/`NodeReparented`/`NodePromoted`/`NodeDemoted` that would create a three-level `comp_*` chain is rejected

## Phase 5.5 — Project vocabulary layer

First-class vocabulary as its own node tier. Addresses silent LLM
drift toward generic meanings by making project-specific term
definitions structured, addressable, and always-included in regen
context. Lands after subcomponent arch docs so the vocabulary
layer is available for every downstream generation (impl, plan,
code) without retroactive backfill of Phases 4 and 5 — existing
approved content keeps its content; new regens after this phase
lands use vocab-aware context assembly.

Vocab is a node tier, not a fragment, because vocab entries are
entities with independent lifecycles (edit/review, promotion
between scopes via reparent, user-creatable outside a flow, and
eventually `vocab_reference` edges between terms). Scope lives
on `parent_id`: null means project-level, `feat_*` means
feature-local, anything else rejected by the reducer.

Content is parseable XML matching the `<vocab-entry>` grammar
(same family as comparch / subcomparch), stored verbatim on
`Node.content`, rendered from XML to prose at context-assembly
time so prompt tokens aren't wasted on raw tags.

- [ ] Alembic migration `b11_vocab_tier` adds `vocab` to `ck_nodes_tier` check constraint via `batch_alter_table`
- [ ] `backend/models/node.py` NODE_TIERS tuple, `backend/graph/ids.py` `Kind.VOCAB`, `backend/graph/events.py` NodeTier Literal widened — no new event class, existing `NodeCreated` / `NodeRenamed` / `NodeReparented` / `NodeDeleted` handle vocab generically
- [ ] Reducer invariant on vocab parent: `_enforce_vocab_parent_constraint` rejects any `NodeCreated` or `NodeReparented` whose target tier is `vocab` and whose `parent_id` is set to anything other than a `feat_*` node. Called from `_apply_node_created` and `_apply_node_reparented` when target tier is `vocab`.
- [ ] New `backend/graph/vocabulary.py` helpers module: `list_project_vocab`, `list_feature_vocab`, `vocab_by_id`, `vocab_by_name`, `reachable_vocab_for_node`. Parity shape with `expansion.py` / `requirements.py` / `subrequirements.py`.
- [ ] Expansion prompt extended with an optional `<vocabulary>` sibling section containing `<term>` elements. Each `<term>` carries `name` + `scope` (+ `feature-alias` when scope is feature) attributes and a single `<vocab-entry>` inner child with `<definition>` (required) + `<disambiguation>` (optional) + `<see-also>` (optional, `<ref name="..."/>` children). Cold-start prompt rejects `to=` form refs; post-mint edit prompt accepts both.
- [ ] Validator extended with `VocabEntry` and `VocabRef` dataclasses and a `validate_vocabulary` function. Enforces structural grammar, required fields, scope rules, feature-alias resolution against the parsed feature list, name uniqueness within scope, and the name-only-at-cold-start rule.
- [ ] `feature_mint` handler extended to project `vocab_*` nodes in the same transaction as `feat_*` nodes. Iteration order matters: features first (populates the alias-to-id map), vocab second (consumes the map to resolve `feature-alias` to `parent_id`). `Node.content` is the raw XML of the `<vocab-entry>` inner block, stored verbatim.
- [ ] `regen_context.py` adds `project_vocab` and `feature_vocab` fields to `RegenContext`, populated by `build_regen_context` via `vocabulary.reachable_vocab_for_node`. New `vocab_summary: str` key in the output of `format_regen_context` and `format_regen_context_for_sub`, produced by a new XML-to-prose formatter in `vocabulary.py`.
- [ ] Every tier's `render_user_prompt` accepts and threads a `vocab_summary` kwarg (requirements, sysarch, subrequirements, comparch, subcomparch, policy_application). Feature expansion is excluded — it generates vocabulary rather than consuming it.
- [ ] Instruction vocabulary adds `CreateVocabEntry(name, content, parent_id)` for direct user creation. Rename / reparent / delete reuse existing `NodeRenamed` / `NodeReparented` / `NodeDeleted` instructions.
- [ ] Light `generate_vocab_entry` handler for feedback → regen flow on existing vocab entries. Small single-entry prompt, validator, draft emission.
- [ ] Routes: `GET /api/projects/{id}/vocabulary` (list), `GET /api/projects/{id}/features/{feat_id}/vocabulary` (per-feature), `GET /api/projects/{id}/vocabulary/{vocab_id}` (detail), `POST /api/projects/{id}/vocabulary/create`, and the four-state feedback/approve/discard/delete/reparent handlers.
- [ ] Full bootstrap chain test extended: stub expansion now emits a `<vocabulary>` section; assertions added that vocab nodes are minted in the correct scope; downstream tier prompts contain vocab context in their assembled prompts.
- [ ] Frontend: `VocabularyList`, `VocabularyEntry` (using existing XML renderer machinery for `<vocab-entry>` / `<definition>` / `<disambiguation>` / `<see-also>` / `<ref>` with per-element visual treatments), `CreateVocabEntryDialog`, `VocabularyPage` routed at `/projects/:id/vocabulary`. Dashboard gets a "Vocabulary" tab; feature detail page gets a feature-local vocab panel.
- [ ] ~80 new tests across validator (~30), mint (~10), regen context (~15), handler + routes (~15), frontend components (~10).
- [ ] Explicitly **out of scope** for this phase: LLM-discovered vocabulary, `vocab_reference` first-class edges (stored cross-references land in the XML from day one; edge emission is a separate one-function follow-up), proliferation guardrails for large vocabularies, automatic linking of term mentions in rendered prose. All straightforward follow-ups.

## Phase 6 — Presentational nodes + domain-parent edges

Unified DAG: domain and presentational share shape, distinguished by
`kind`. Presentational is strictly layered after domain.

- [ ] Presentational variants of feature / responsibility / component prompts
- [ ] `domain_parent` edge type already in the schema — add editor support
- [ ] Structured UI #6: domain-parent editor (same Cytoscape, different edge type / color)
- [ ] Regen prompt context for presentational: reads domain `pubapi` AND `domain-parent` sibling specs

## Phase 6.6 — Reference node tier

First-class reference documents as their own node tier. Addresses
the gap where supplemental content — DSL specs, deployment
runbooks, cross-component invariants docs — has no structural
home: too standalone to be a fragment, too shapeless to be a
component, not a term definition so not vocabulary. Lands after
the Phase 6 backend slice and before Phase 7 fan-in synthesis.
Existing approved content keeps its state; new regens after this
phase lands pick up ref context via the `reference` edge walk.

Ref is a tier, not a fragment, because refs have independent
lifecycles, participate in edges, and need stable IDs and their
own review lifecycle. The `reference` edge type they use is a
general-purpose advisory-context edge not specific to refs — any
node can draw a `reference` edge to any other node to include its
content in regen context. The reducer enforces `parent_id = null`
on refs — refs are never scoped to another node the way vocab is
scoped to features. Content is parseable XML matching the
`<reference>` grammar, stored verbatim on `Node.content`, and
rendered from XML to prose at context-assembly time so prompts
don't pay tokens for raw tags. **Refs are not frozen after
approval** — `UpdateReference(ref_id, feedback)` works on any ref
in any state, unlike the bootstrap tiers, because refs don't mint
children and therefore have no downstream desync to guard.

- [x] Alembic migration `bXX_ref_tier` widens `ck_nodes_tier` to include `ref` **and** widens `ck_edges_edge_type` to include `reference`, both via `batch_alter_table`. Single migration covers both schema changes.
- [x] `backend/models/node.py` `NODE_TIERS` tuple + `backend/graph/ids.py` `Kind.REF` + `backend/graph/events.py` `NodeTier` Literal widened, plus `EDGE_TYPES` tuple widened with `reference`. No new event class — `NodeCreated` / `NodeDeleted` / `FragmentUpdated` / `EdgeCreated` handle refs generically.
- [x] Reducer invariant `_enforce_ref_parent_constraint`: `NodeCreated` or `NodeReparented` whose target tier is `ref` and whose `parent_id` is not `None` is rejected at event-apply time. Mirror of the vocab invariant.
- [x] New `backend/graph/references.py` helpers module: `list_project_references`, `reference_by_id`, `reference_by_name`, and `referenced_content_for_node(source_id)` which walks outgoing `reference` edges from *any* node id and dispatches on each target's tier to pull the right chunk (`ref_*` → `Node.content` rendered to prose, `comp_*` → `pubapi` fragment, `policy_*` → rationale, feat/resp → `Node.content`), plus an XML-to-prose formatter matching the style of `vocabulary.py`. Walker is source-tier-agnostic so comparch, subcomparch, and ref regens share one code path.
- [x] New `backend/graph/prompts/reference.py` with a generation prompt template that takes `(seed_description, referenced_content_summary, prior_approved, prior_pending, feedback, parse_error)`. The `referenced_content_summary` is the rendered content of every node this ref has an outgoing `reference` edge to — the same partition every other tier sees, populated by the shared walker. Generic prompt, not per-tier.
- [x] New `generate_reference` handler registered as `v2.generate_reference`. Uses the existing `run_parse_validate_loop` helper with a new `validate_reference` validator. `UpdateReference(ref_id, feedback)` triggers regen regardless of the ref's current approved state (no freeze check).
- [x] Validator extended with a `Reference` dataclass and `validate_reference` function. Grammar: `<reference>` root, required `<title>` (prose), required `<body>` (opaque markdown inside — validator doesn't parse body content), optional `<see-also>` with `<ref to="ref_..."/>` children. Full `<reference>` XML is stored verbatim on `Node.content`.
- [x] `RegenContext` grows a `referenced_content: dict[str, str]` field (target_node_id → rendered content chunk). `build_regen_context` populates it by walking `reference` edges outgoing from the regen target (works for comp / subreqs / ref / any tier). Every tier's `render_user_prompt` that currently accepts `vocab_summary` additionally accepts `referenced_content_summary`, rendered by a new formatter as a "References" section in the prompt. Own budget partition alongside vocab / pubapis / policy context.
- [x] Routes: `GET /api/projects/{id}/references` (list), `GET /api/projects/{id}/references/{ref_id}` (detail), `POST /api/projects/{id}/references/create` (accepts `seed_description` + `related_nodes`), and four-state `feedback` / `approve` / `discard` / `delete` handlers per ref. Edge-edit routes: `POST /api/projects/{id}/edges/reference` takes `(source_id, target_id)` and emits a `reference` edge; `DELETE` with matching params removes it.
- [x] Instruction vocabulary adds `CreateReference(seed_description, related_nodes)`, `UpdateReference(ref_id, feedback)`, `AddReference(source_id, target_id)`, `RemoveReference(source_id, target_id)`. Deletion reuses `NodeDeleted`. All flow through the pending-change queue.
- [x] Frontend: `api/references.ts` with zod schemas + fetchers, `useReferenceQueries` / `useReferenceMutations` hooks, `ReferencesList`, `ReferencePanel` (using the existing XML renderer machinery), `CreateReferenceDialog` (with `related_nodes` pre-filled from invocation context), `ReferencesPage` routed at `/projects/:id/references`. Dashboard gets a "References" tab next to "Vocabulary". Component / feature / policy detail pages grow a "Create reference" affordance. The ReferencePanel shows connected nodes as a list with add/remove affordances.
- [x] End-to-end bootstrap chain test extended: seed one `ref_*` node attached via `reference` edges to a top-level comp. Assert (a) the ref's rendered content lands in that comp's comparch prompt in the "References" section, and (b) when the ref is regenerated via `UpdateReference`, the ref's own regen prompt contains the comp's pubapi in its "References" section.
- [x] ~60 new tests across validator, handler, reducer invariant, regen context, routes, and frontend components.
- [ ] Explicitly **out of scope** for this phase: LLM-driven `reference` edge declaration; project-level "always visible" ref bucket; staleness propagation across `reference` edges (Phase 9); cross-ref linking in rendered artifact prose; LLM-discovered references; `<see-also>`-to-edge synchronization. All straightforward follow-ups; none load-bearing for the MVP.

## Phase 7 — Domain fan-in synthesis nodes

Bound the input set to presentational counterparts.

- [x] Auto-mint one fan-in node (`fanin_*`) per domain component with subcomponents, **unconditionally** — minted whether or not a presentational counterpart currently exists, so adding a domain-parent edge later is a pure edit, not a mint-on-the-fly
- [x] Fan-in handler: reads all subcomponent implementation nodes, writes a synthesis doc
- [x] Feeds presentational counterparts (current or future) via `domain_parent`
- [x] Excluded from review scoping (mechanical, not user-editable)
- [x] Staleness trigger: any subcomponent implementation change regenerates the fan-in

## Phase 8 — Implementation nodes (leaves)

Implementation nodes (`impl_*`) are separate leaf nodes, distinct from
the parent component's `<technical-specification>` section. One impl
node per subcomponent and per un-fanned-out component.

- [x] `impl` tier node minted as leaf under each subcomponent and each un-fanned-out component
- [x] Components with subcomponents have no impl node of their own — their impl lives in their subcomponents' impl nodes
- [x] Implementation regen prompt: parent `techspec` + parent `pubapi`/`privapi` fragments + dep `pubapi` fragments
- [x] Uses shared regen helper from Phase 4
- [x] Destructive-edit gate only; non-destructive impl edits propagate automatically to plan nodes

## Phase 9 — Staleness ledger & fanout decision

The diff helper and fragment-level diffs already landed in Phase 4.
What remains for propagation is the bookkeeping layer that decides
*what* to regen next.

- [ ] Staleness ledger: "this node is stale w.r.t. neighbor N at offset O"
- [ ] Crude fanout decision (MVP: regen all downstream; refinement is post-MVP)
- [ ] Wire the destructive-op gate into the fanout decision — destructive edits halt the cascade, non-destructive edits flow through

## Phase 10 — Layered DAG view

A single navigable view of the whole project graph. Lands as soon
as enough structural tiers exist to be interesting — features,
responsibilities, top-level policies, components and their
dependencies, subresponsibilities, subcomponents, impls. Reads
projections and edges directly; emits no events. The view becomes
the primary way users navigate the structured model, and is the
host surface every Phase 11 structured edit UI drops into via
contextual affordances on a selected node.

**Top-level view** shows the whole project in layers:

- **L0 — features** (flat, no internal deps): side-by-side cards
- **L1 — top-level responsibilities** (flat): side-by-side cards
- **L2 — top-level policies** (flat): side-by-side cards. Their
  `policy_application` edges don't land until each component's
  comparch pass runs, so early in a project's lifecycle they're
  visible but disconnected from the component layer.
- **L3+ — components**, arranged in dependency-topological
  layers (sources at the top, sinks at the bottom, one tier of
  layer per dependency hop)
- Edges shown: `decomposition` (feat → resp), resp → comp 1:1
  assignment (inferred from `parent_id` or the 1:1 mapping
  state, not a stored edge), `policy → resp` "required"
  reference, `policy_application`, `dependency`, `domain_parent`

**Drill-into-component view** swaps the canvas when a component is
double-clicked or long-pressed:

- **L0 — external context**: the external features / responsibilities
  / top-level policies that trace *into* this component via the
  DAG (computed as a reverse walk from the component)
- **L1 — component-local policies** (minted at this component's
  comparch approval)
- **L2 — subresponsibilities** (minted at this component's
  `subreqs_*` approval)
- **L3+ — subcomponents**, arranged in dependency-topological
  layers within this component's subtree
- **L-bottom — fan-in synthesis node** (`fanin_*`) if any
- Edges shown: `decomposition` (top_level_resp → subresp), subresp
  → subcomp 1:1 assignment, component-local `policy_application`,
  inner `dependency`, outer edges to/from external context layer
- **impls / plans / codegen**: structurally these are leaves
  hanging off each subcomponent. Hidden by default to keep the
  canvas readable. Reveal-on-click (clicking a subcomponent
  expands its impl / plan / codegen leaves inline). Decision
  about precisely how to position them in the layer stack is
  deferred to this phase's implementation pass.

**Interaction model:**

- **Single tap / click** on a node selects it and highlights all
  of its edges plus the full reachable subgraph to leaves (DFS
  downstream from the selected node). Upstream reachable set is
  also highlighted but distinguished visually so "what implicates
  me" is readable separately from "what do I implicate".
- **Double-tap / long-press** on a `comp_*` node drills into its
  internal view. The browser URL updates so the drill state is
  shareable and back-button-navigable.
- **Escape / back button** returns to the parent view.
- **Edge hover** shows the edge type + source/target ID summary.
- Mobile: tap to select, double-tap to drill, long-press for
  context menu.

**Layout:**

- Libraries already in `package.json`: `cytoscape`, `cytoscape-elk`,
  `dagre`, `elkjs`, `react-cytoscapejs`, `@xyflow/react`. Pick
  one during implementation — cytoscape + elk is the likely
  default for the tap/highlight ergonomics and layered-layout
  support.
- Layer assignment is a topological sort on `dependency` edges
  within each layer-capable tier. Cross-layer edges (feat→resp,
  resp→comp assignment, policy_application) are drawn as long
  arcs that don't participate in layer assignment.

**Out of scope for this phase:**

- Structural edits — the DAG view is read-only for the structure.
  Phase 11 adds the structured edit UIs that run on top of a
  selected DAG node.
- Animation, transition effects, multi-select, export to SVG/PNG.
  All post-MVP polish.
- Non-trivial layout caching — MVP recomputes on each projection
  change, which is fast enough for < 500 nodes.

**Data dependencies:**

- Phases 3–8 must have landed for the view to be useful — before
  Phase 3 there are only features, which is a boring flat layer.
- Phase 9's staleness ledger is orthogonal but integrates
  naturally: nodes with pending upstream changes get a visual
  marker on the DAG.

## Phase 11 — Pending-change queue UX + structured edit UIs

The foundation already has the queue primitive. This phase is building
all six structured edit UIs on top of the minted model from Phases 3
and 4, and wiring them into the pending-change queue. **No UI mutates
the model directly — every action produces prose instructions.**

- [ ] Queue panel: list queued instructions, discard button (free undo), "Apply changes" button
- [ ] "Apply" enqueues a single `v2.apply_instructions` job; sequential execution invariant
- [ ] Rename instructions rewrite prose via the LLM, not direct DB update
- [ ] Structured UI #1: feature → responsibility mapping (drag-drop, assign-only)
- [ ] Structured UI #2: responsibility → component mapping (drag-drop, assign-only)
- [ ] Structured UI #3: component / subcomponent decomposition (Cytoscape, create/move/delete)
- [ ] Structured UI #4: subresponsibility → subcomponent mapping (drag-drop)
- [ ] Structured UI #5: dependency editor (Cytoscape, with cycle prevention)
- [ ] Structured UI #6: domain-parent editor (same Cytoscape, different edge type / color)
- [ ] Mobile interaction: tap-to-select + tap-to-place for drag-drop, tap-two-nodes for graph editors
- [ ] All six UIs support promotion / demotion between tiers without changing IDs

## Phase 12 — Batched review flow

Review pass = component. MVP ships a simple per-component walk; the
polished combined-navigable-diff UI is post-MVP.

- [ ] **AI self-review pass.** Every generated draft runs through an
  AI review step before landing in the human review queue. The status
  chain becomes `generating → ai_reviewing → awaiting_review`. The
  self-review LLM call reads the draft + its regen context and
  produces structured feedback (quality score, recommendation,
  notes). If the score is below a configurable threshold, the draft
  is automatically regenerated with the self-review feedback
  injected — up to a configurable loop limit (default 1 retry).
  Drafts that pass self-review land in `awaiting_review` for human
  review. Drafts that exhaust the retry budget land in
  `awaiting_review` anyway but carry a "self-review flagged" marker
  so the reviewer knows the AI wasn't satisfied. Self-review
  criteria are bundle-configurable per tier.
- [ ] `ViewRecorded` event is already in the vocabulary — use it
- [ ] Pin event offset on first review open per batch
- [ ] Point-in-time reconstruction via `rebuild_projections(up_to_offset=...)`
- [ ] **Snapshot cache from day one** — key on `(project_id, event_offset)`, store reduced projection; snapshots are immutable (never invalidated, only garbage-collected), so the cache is a pure optimization on the log-walk path
- [ ] Per-component review UI: walks pending nodes in topological order
- [ ] Fragment diff rendering (before/after side-by-side per fragment)
- [ ] Fan-in nodes skipped in review scoping
- [ ] UI distinguishes **destructive** (blocking, requires approval) from **non-destructive** (informational, already propagated) changes so users learn which ones actually need attention
- [ ] Accept on a destructive change releases the halted cascade; accept on a non-destructive change is informational only

## Phase 13 — Change summaries

- [ ] Every generation prompt appends a change-summary section
- [ ] Parser strips the summary from stored content, writes to a structured change log
- [ ] Queryable audit history endpoint
- [ ] Feeds into review UI (the summary is what gets shown as the diff header)

## Phase 14 — File manifest + plan nodes + code generation leaf pass

The bottom of the DAG. Three artifacts land together here because
they're mutually dependent: the manifest defines territory, plans
are territory-limited, and code generation consumes plans.

**File manifest (`manifest_*`):**
- [ ] New singleton `manifest` tier node per project, generated after the component tree is first minted
- [ ] Manifest prompt: component tree + project language settings + framework conventions → file/folder → owning component mapping
- [ ] Reviewable like any other node (prose feedback, regen, approval flow) — the user can say "controllers belong to the presentational layer"
- [ ] Regenerated on component-tree changes (create/delete/promote/demote/merge/split at the `comp_*` layer), not on every edit
- [ ] Generate-parse validation loop
- [ ] Conflict detection: two components claiming the same file is a parse error
- [ ] Routes mirror expansion / sysarch
- [ ] UI: read-only manifest view with prose feedback

**Plan nodes (`plan_*`):**
- [ ] `plan` tier node, generated when an impl node changes (or when the user re-opens review on an existing plan)
- [ ] One "live" plan per impl at a time via a current-pointer on the impl node; old plans retained in the event log as consumed
- [ ] Plan prompt: current impl + prior impl + dep `pubapi` fragments + project language settings + manifest entries for the owning component → structured list of (file, region, change) tuples + prose explanation
- [ ] Plan is a parseable output: generate-parse validation loop (retry-then-escalate)
- [ ] **Reviewable with prose feedback like any other node.** A plan the user doesn't like is iterated on in place, not thrown away and silently re-derived.
- [ ] **Independently gated** from the impls that produced them — approving an impl is permission for the plan to regenerate; approving the plan is permission to write code. Plan approval is a destructive-class gate.
- [ ] Plans read earlier plans + their generated code from within the same batch, so cross-impl coherence falls out of dep topo order
- [ ] **Territory enforcement:** a plan that lists file changes outside its owning impl's manifest territory fails parse validation and triggers the retry loop
- [ ] Plan marked consumed once code generation runs against it; event log retains it for audit

**Code generation:**
- [ ] Per-project language setting (Catapult = Elixir), inherited from the sysarch `techspec`
- [ ] Code regen prompt: approved plan + dep `pubapi` fragments + language conventions (no impl node)
- [ ] Language-specific validator (compile / typecheck hook) as parse-validate loop
- [ ] Retry-then-escalate on persistent failures
- [ ] Dependency topological execution order, one plan at a time
- [ ] Generated code written to the project's git repo (v1 git plumbing survives)
- [ ] Code generation is **territory-limited** — refuses to write outside the plan's validated territory even if the plan somehow slipped one through (defense in depth)

## Phase 15 — Catapult smoke test

The acceptance test for v2. No migration from v1; rebuild from scratch.

- [ ] Load Catapult's input doc into a fresh v2 project
- [ ] Walk Phases 1 through 13 end-to-end, approving at each gate
- [ ] Verify generated Elixir compiles
- [ ] Capture feedback loop latency at each tier (is the 2s poll interval enough?)
- [ ] Identify which post-MVP deferred items are actually blocking day-to-day use
- [ ] Export the resulting project via Phase 16 and verify Catapult's input parser can ingest the bundle

## Phase 16 — Project export for external consumption

A one-shot "export this project" action that reads the v2 graph
and transcribes it back into prose documents a downstream tool
(specifically Catapult) can ingest. Exists because the v2
graph is rich enough that a human-readable round-trippable
snapshot is genuinely useful — for handing the project off,
archiving an approved state, or feeding it into a tool that
doesn't speak the v2 model natively.

The export is **read-only** and doesn't touch the DAG. It walks
the projections (features, responsibilities, components, arch
docs, impls, policies, manifest) in a deterministic order and
renders each to markdown with the XML sections preserved as-is
(per "tags are displayed, not stripped"). The output is a
bundle of files rather than one monolith — one file per
top-level comp_* with its arch doc content, one for reqs, one
for sysarch, one for the feature list, etc. — so Catapult's
import can consume them piecewise.

Catapult's input-doc format is the target shape. Each exported
document should be something Catapult's input parser would
accept unchanged if dropped in.

- [ ] Export handler that runs synchronously in response to a
      UI button; no pipeline job needed (read-only, seconds-scale)
- [ ] Walks projections in deterministic order: expansion →
      reqs → sysarch → per-component arch docs → per-subcomponent
      arch docs → impls → plans → manifest
- [ ] Renders each node's content + fragments as markdown, with
      XML tags preserved verbatim and a frontmatter block
      carrying the stable `<kind>_<8 chars>` ID plus metadata
      (tier, name, parent, timestamps, group_label if feat_*,
      is_implicit if feat_*)
- [ ] Bundles into a zip archive with a manifest.json describing
      what's inside and its order
- [ ] Reviewable in the UI as a file tree before download (so
      the user can spot-check what they're about to get)
- [ ] New endpoint: `GET /api/projects/{id}/export` returning the
      archive as a streamed response
- [ ] UI: "Export" button on the project dashboard header;
      downloads the archive
- [ ] Tests: round-trip a canonical project through export and
      confirm the structure + content match what's in the
      projection
- [ ] Documented format stays stable — Catapult's import is
      coupled to it, so format changes go through a migration
      note

Post-MVP candidate for round-two: bi-directional sync (import
an edited Catapult bundle back into v2). MVP just exports.

---

## Post-MVP (deferred, tracked for awareness)

Per the architecture doc — nothing here is load-bearing for the first
shippable product.

- [ ] Fanout decision refinement (LLM-driven "which children actually changed")
- [ ] Vector search review augmentation
- [ ] Two-pass upward propagation automation
- [ ] Polished combined-navigable-diff review UI with version-dropdown navigation (MVP ships a simpler per-component walk; auto-propagation of non-destructive changes is already MVP)
- [ ] View-history snapshot optimization beyond the basic Phase 12 cache
- [ ] Multi-user concurrency on the pending-change queue
- [ ] WebSocket push instead of polling

---

## How to use this file

- Open a new phase by writing a plan under `/root/.claude/plans/` (same shape as `cheeky-soaring-token.md`) before coding.
- Flip `[ ]` → `[~]` when the plan is approved and work starts.
- Flip `[~]` → `[x]` only when the phase is merged and the acceptance test in the phase's own plan is green.
- Don't add new phases without updating the architecture doc's MVP scope section first. Scope creep dies here.
