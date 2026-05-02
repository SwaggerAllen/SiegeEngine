# Plan: SiegeEngine v2 Phase 14 — File manifest + plan nodes + code generation leaf pass

## Resume state

Plan was written and approved on the branch `claude/debug-panel-copy-options-ler92`. Implementation hasn't started — context ran short before PR0 began. To resume in a fresh session:

1. Confirm the branch's HEAD includes the commit that landed this plan file (look for `docs(plans): phase 14 plan`).
2. Read this file end-to-end to absorb the design.
3. Begin with PR0 (refs schema migration) per the section below.
4. Each PR has its own scope; each lands independently. Don't bundle them.

Key orientation:
- Phase 14 design lives in `docs/architecture/v2-rearchitecture.md` (§Project references + §Code generation territory) and `docs/architecture/v2-roadmap.md` (Phase 14, bullets now in sync with reality).
- Catapult v3 platform spec describes the `role: manifest` tier flag at §A.3.1 / §A.3.1a.
- Catapult default-bundle doc describes per-scope manifests at §6.4 and the framework-agnostic stance at §6.6.
- User-approved recommendations: 5 PRs as drafted (PR0 → PR4 sequence), and code as a first-class tier (`code_*`).
- Last-known commit on the branch carrying this plan: see `git log` after the `docs(plans):` commit.

## Context

Phase 14 is the bottom of the v2 DAG: turn approved architecture into actual code in the project's git repo. Three new tiers (manifest, plan, code) plus a schema migration on refs (`territory_path` + `role`). Per the roadmap (now synced) and the architecture / catapult docs (recently expanded), the design is mostly settled — what remains is implementation across a sequence of PRs that each plug into the existing tier-generation playbook.

The intended outcome: a project that's been walked through Phases 1–13 produces a buildable codebase in its git repo, with manifests defining territory, plans defining structured changes, and code generation executing under territory-limited validation. Phase 15's Catapult smoke test runs against this end-to-end.

The playbook is established. Per the exploration:
- `backend/graph/handlers/_tier_generation.py` is THE shared driver for tier generation. Adding a new tier = instantiate one `TierGenerationConfig` + a thin handler that calls `run_tier_generation()`.
- `backend/graph/bootstrap_routes.py` defines `BootstrapTierConfig` for the four-state route pattern (`get / feedback / approve / discard`). Reused by every tier.
- Refs (Phase 6.6) was the most recent tier addition and is the closest template — single-scope, parseable XML, validator + route + frontend panel.

## PR sequence

Five PRs, each landable independently. Each except PR0 follows the established new-tier playbook.

### PR0 — Refs schema migration: `territory_path` + `role`

Smallest, isolated. Lands first so PR1's manifest can already account for territory-bearing refs.

**Backend:**
- Alembic migration adding `territory_path: str | None` and `role: str | None` columns to the `refs` table (or wherever ref content lives — confirm during impl).
- Update ref's parseable `<reference>` grammar to include optional `<territory-path>` and `<role>` siblings to `<title>` / `<body>` / `<see-also>`.
- `validate_reference` (`backend/graph/parsers/validators.py`) extended to parse + validate the two new optional elements.
- `referenced_content_for_node` walker (`backend/graph/references.py`) updated: when target ref has `territory_path` set, render metadata-only (`territory_path`, `role`, `<title>`) by default. Add an `inline_content` flag on `reference` edges (new edge attribute; tiny migration on `edges`).
- Routes / `CreateReference` / `UpdateReference` accept the new fields.

**Frontend:**
- `parseReference` / `buildReferenceXml` in `frontend/src/api/references.ts` round-trip the two new fields.
- `ReferencePanel` UI gains optional inputs for `territory_path` (text) and `role` (textarea).

**Tests:**
- Validator: ref with territory_path + role parses; ref without them parses (back-compat); ref with malformed paths rejected.
- Walker: territory-bearing ref renders metadata-only by default; `inline_content` flag flips to full body.
- Round-trip: edit-via-feedback preserves the new fields.

### PR1 — Manifest tier (per-scope, with role flag)

The biggest PR. Three architectural-scope variants of the manifest land together since the per-scope design is load-bearing.

**Schema:**
- `NODE_TIERS` += `"manifest"`; `Kind.MANIFEST = "manifest"`; `NodeTier` Literal widened.
- Migration `bXX_manifest_tier` widens `ck_nodes_tier`. No new edge types — manifests use existing structural relationships.
- Manifest nodes carry `parent_id` pointing at the scope owner: project-level manifest has `parent_id = null`; comp-level manifest has `parent_id = comp_*`; subcomp-level has `parent_id = comp_sub_*`. Scope is implicit from parent's tier.

**Reducer:**
- `_enforce_manifest_uniqueness`: at most one manifest per `(project_id, parent_id)` pair. `NodeCreated` for a duplicate is rejected.

**Tier-generation handler (`backend/graph/handlers/generate_manifest.py`):**
- Follows the `generate_reference.py` template.
- `ManifestState` dataclass: scope owner (project / comp / subcomp), child set, project techspec, applicable refs with `territory_path`, prior approved + pending drafts.
- `gather_manifest_state` reads the scope's local children + the project's techspec for framework signals + refs claiming paths inside the scope.
- `render_manifest_prompt` produces a parseable `<manifest>` block. Children claims as `<claim path="..." owner="..." kind="folder|file"/>` entries; refs that override are rendered into the prompt context so the LLM knows about file-level overrides without enumerating them itself.
- `validate_manifest` enforces grammar + per-claim well-formedness (path is a valid relative path; owner is a known node id; kind matches the tier — comps/subcomps emit `folder`, refs/impls emit `file`).
- `MANIFEST_CONFIG: TierGenerationConfig` plugs into `run_tier_generation`.

**Specificity-wins precedence:**
- Implemented as a post-validation step inside `validate_manifest`: walk all claims, build the `(path, claim_kind, owner)` set, reject if same-specificity claims collide. The override pattern (file claim shadowing folder claim) is allowed and recorded.

**Global cross-cut pass:**
- New module `backend/graph/manifest_validation.py` with `run_global_pass(db, project_id) -> GlobalFindings`.
- `GlobalFindings` dataclass: collisions (same-specificity duplicates across scopes), orphans (paths in repo with no claimant), disk-vs-content drift on territory-bearing refs.
- Called explicitly: (a) by a project-wide health endpoint the UI hits, (b) by Phase 14's code-gen leaf pass before it runs (gate). NOT called automatically on every manifest commit (too expensive at scale).
- Drift detection requires reading the project's git repo — uses the v1 git plumbing already in place.

**Routes (`backend/graph/routes.py`):**
- `MANIFEST_CONFIG: BootstrapTierConfig` plugs into the four-state pattern. Scoped per-manifest by `(project_id, parent_id)`.
- Routes: `get / feedback / approve / discard` per manifest. Plus `GET /api/projects/{id}/manifest/global-findings` for the cross-cut pass.

**Per-scope regen triggers:**
- Post-persist hook: structural events within a scope (child node mint / delete / reparent) invalidate that scope's manifest only. Implementation: a new `post_persist_hook` on the relevant tiers' `TierGenerationConfig` enqueues a `v2.generate_manifest` job for the affected scope. No other manifests are touched.

**Frontend:**
- New `ManifestPanel` component, four-state. One panel per scope, mounted on the corresponding entity's workspace page (project landing page for project-level; comp page for comp-level; subcomp page for subcomp-level).
- New project-wide "Manifest health" page consuming `global-findings`. Lists collisions / orphans / drift with click-through to the offending node.
- `tabScope.ts` adds a `manifest` tab to comp / subcomp pages alongside the existing artifact tabs.

**Tests:**
- Validator: claim parsing, specificity-wins enforcement, malformed path rejection.
- Handler: gather_state pulls correct scope-local children; rendering includes ref territories.
- Reducer: manifest uniqueness invariant.
- Cross-cut: collision / orphan / drift detection on synthetic project state.
- Routes: four-state lifecycle per scope; global-findings endpoint shape.
- Per-scope regen triggers don't fire across scopes.

### PR2 — Plan tier (per-impl, structured tuples)

Once manifests exist with validated territory, plans can use territory as their parse-validation target.

**Schema:**
- `NODE_TIERS` += `"plan"`; `Kind.PLAN`; `NodeTier` widened.
- Migration `bXX_plan_tier`.
- Plan nodes have `parent_id = impl_*`. One "live" plan per impl via a `current_plan_id` pointer on the impl node (small additive column).

**Reducer:**
- `_enforce_plan_parent_constraint`: plan's `parent_id` must be an `impl_*` node.
- New event `PlanConsumed(plan_id)` flips a `consumed: bool` flag on the plan and updates the impl's `current_plan_id` to null.

**Tier-generation handler (`backend/graph/handlers/generate_plan.py`):**
- `PlanState` dataclass: current impl content, prior impl content (if any), dep `pubapi` fragments, manifest territory entries for the owning comp/subcomp, project language settings, prior plans + their generated code from within the same batch.
- `render_plan_prompt`: produces `<plan>` with structured `<change>` tuples — `<change file="..." region="..." kind="add|modify|delete">prose</change>` — plus a `<rationale>` paragraph.
- `validate_plan`:
  - Grammar enforcement.
  - **Territory enforcement:** every `<change file="...">` path must fall inside the owning impl's manifest territory (queried via the manifest projection). Out-of-territory changes fail validation → retry loop.
  - Region well-formedness (line ranges or symbol identifiers).
- `PLAN_CONFIG: TierGenerationConfig`.

**Independent gating:**
- Plan approval is a destructive-class gate (per the architecture doc). Approving a plan permits code generation. Approving an impl does NOT permit plan regeneration to land code; the plan needs its own approval.
- Implementation: standard four-state. The `has_been_approved` predicate on `BootstrapTierConfig` reads the plan's own approval state, not the impl's.

**Routes:**
- Standard four-state per plan, scoped by impl id.
- New endpoint: `POST /api/projects/{id}/impls/{impl_id}/plan/regenerate` to fire a fresh plan job after impl edits.

**Frontend:**
- `PlanPanel` component. Renders `<change>` tuples as a structured list with file paths, regions, and rationales. Plan-level approval button is distinct from impl-level.
- `tabScope.ts` adds a `plan` tab to impl pages.

**Tests:**
- Validator: territory enforcement (in-bounds + out-of-bounds cases).
- Handler: state gather pulls dep pubapis + manifest territory.
- Cross-impl coherence: plans within a batch read prior plans' content + their generated code.
- Independent gating: approving the impl doesn't approve the plan.

### PR3 — Code generation tier (`code_*`)

Lands after plans exist. Per-plan, leaf of the DAG.

**Schema:**
- `NODE_TIERS` += `"code"`; `Kind.CODE`; `NodeTier` widened.
- Migration `bXX_code_tier`.
- Code nodes have `parent_id = plan_*`. One per plan.

**Reducer:**
- `_enforce_code_parent_constraint`: code's `parent_id` must be a `plan_*`.
- A `code_*` node can only be created when its parent plan is in the approved state — enforced at handler time (not at reducer level since the reducer doesn't know about approval semantics).

**Tier-generation handler (`backend/graph/handlers/generate_code.py`):**
- `CodeState` dataclass: approved plan content (the `<change>` tuples), dep `pubapi` fragments, project language settings, manifest territory.
- `render_code_prompt`: per-language scaffolding around the plan tuples. Language registry (see below) supplies the scaffolding.
- `validate_code`: language-specific compile/typecheck hook (see below). Failure → standard parse-validate retry.
- `CODE_CONFIG: TierGenerationConfig` with `thinking_effort=None` (code gen is mechanical given a good plan; max thinking is wasted here).

**Language registry (`backend/graph/code_languages/`):**
- `code_languages/__init__.py`: registry mapping language string → `LanguageHooks(validate, build_prompt_scaffolding)`.
- `code_languages/elixir.py`: shells out to `mix compile --warnings-as-errors`.
- `code_languages/python.py`: shells out to `ruff check && python -m py_compile` (for SiegeEngine self-hosting).
- Project's language is read from sysarch's `<technical-specification>` at gen time. Default = "python".

**Persistence to git:**
- The v1 git plumbing exists. On code approval, write the generated content to the territory-claimed paths in the project's git repo as a single commit. Commit message includes the plan id and the affected impl id for traceability.
- Territory enforcement at write time: refuse to write outside the plan's validated territory (defense in depth — the plan validator should already catch this).

**Routes:**
- Standard four-state per code node.
- `POST /api/projects/{id}/plans/{plan_id}/generate-code` triggers code gen against an approved plan.

**Frontend:**
- `CodePanel` component. Renders the generated diff (uses an existing diff viewer or a simple side-by-side). Approval button writes to git.
- `tabScope.ts` adds a `code` tab to plan pages.

**Tests:**
- Language hook registry: lookup, invocation, failure paths.
- Validator: compile failure escalates after N retries.
- Persistence: territory enforcement at write time.
- End-to-end: a small approved plan produces compilable code on disk.

### PR4 — Integration polish + workflow gates

Lands after PR0-PR3. Smaller integration work that rounds Phase 14 out.

**Backend:**
- Code-gen leaf pass refuses to run if the global cross-cut pass has unresolved findings. Surfaces a clear error pointing at the manifest-health page.
- Global cross-cut pass runs automatically before every code-gen invocation as a gate.

**Frontend:**
- Manifest-health → plan-review → code-review walking flow on the workspace page so users can drive the chain.
- Status badges on impl / plan / code nodes in the DAG (extend the existing `generation_running` pulsing-amber).
- Plan tab + Code tab on the comp page's drilldown view (the per-comp Decomposition tab gains plan/code visibility).

**Tests:**
- E2E: walk a small project from sysarch through code generation in one test (`tests/v2/test_phase_14_e2e.py`).

## Critical files

**Backend (new):**
- `backend/graph/handlers/generate_manifest.py`
- `backend/graph/handlers/generate_plan.py`
- `backend/graph/handlers/generate_code.py`
- `backend/graph/manifest_validation.py` (global cross-cut)
- `backend/graph/code_languages/{__init__,elixir,python}.py`
- Three Alembic migrations.

**Backend (modified):**
- `backend/models/node.py` — `NODE_TIERS`, possibly new edge attributes
- `backend/graph/ids.py` — new `Kind` values
- `backend/graph/events.py` — `NodeTier` Literal, possibly new event types
- `backend/graph/reducer.py` — three invariants
- `backend/graph/parsers/validators.py` — three new validators
- `backend/graph/routes.py` — three `BootstrapTierConfig` instances + scope-aware routing
- `backend/graph/references.py` — territory-aware rendering + `inline_content` edge flag handling
- `backend/graph/handlers/_tier_generation.py` — only if a hook needs widening (likely not)

**Frontend (new):**
- `src/api/manifests.ts`, `src/api/plans.ts`, `src/api/codeGen.ts`
- `src/components/ManifestPanel.tsx`, `PlanPanel.tsx`, `CodePanel.tsx`
- `src/pages/ManifestHealthPage.tsx` (or analogous)

**Frontend (modified):**
- `src/components/nav/tabScope.ts` — manifest / plan / code tabs
- `src/components/nav/NavDetail.tsx` — dispatch to new panels
- `src/components/graph/elements.ts` + `tierFilter.ts` — pin manifest/plan/code in `FIXED_BOTTOM_TYPES` or as their own band
- `src/api/references.ts` + `ReferencePanel.tsx` — `territory_path` + `role` round-trip

**Reuse:**
- `run_tier_generation()` driver — three new tiers plug in directly.
- `BootstrapTierConfig` / four-state route pattern — three new tiers reuse.
- `makeBootstrapApi()` factory on the frontend — three new tiers reuse.
- `DagCanvas` — manifest / plan / code nodes appear in the DAG with correct layer pinning.
- `tier-ops` panel — Reset All / Regen From Reviews / Resume Tier work for the new tiers automatically once their `BootstrapTierConfig` is registered with the tier-ops registry.

## Verification

Per-PR:
- All v2 backend tests green: `tests/v2/ -q`
- ruff, ruff format, mypy clean
- Frontend: `npx tsc -b --noEmit --force`, `npm run lint`, `npx vitest run`, `npx vite build`
- Each tier follows the existing playbook so the test density should match Phase 6.6 (~60 new tests per tier).

End-to-end (lands as part of PR4):
- New `tests/v2/test_phase_14_e2e.py` walks a small fixture project from sysarch through approved code, asserting on:
  - Per-scope manifests minted in correct dependency order
  - Global cross-cut pass returns clean findings
  - Plan respects manifest territory; territory-violating plans get rejected and retried
  - Code commits land in the project's git repo
  - Disk-vs-content drift on a territory-bearing ref surfaces as a global-pass finding

Phase 15 (Catapult smoke test) consumes this end-to-end verification on a real-world input doc.

## Decisions taken in this plan

- **Manifest grammar = XML** matching the existing tier conventions (`<manifest><claim path="..." owner="..." kind="folder|file"/>...</manifest>`).
- **Global cross-cut pass = explicit + on-demand**, not background. Surfaces in the UI; runs automatically as the code-gen gate.
- **Languages = Elixir + Python** for v2. Bundle authors who want more languages register hooks in `code_languages/`.
- **Disk-vs-content drift = surface, not auto-fix**. Listed as a global-pass finding that requires explicit user action (re-approve the ref or edit it via feedback).
- **Cross-batch plan reads = within-batch only.** Plans see prior plans' generated code from within the same batch but not across batches; that's a complexity-vs-value trade we punt to post-MVP.
- **PR0 (refs migration) lands before PR1 (manifest tier)** so the manifest design fully accounts for territory-bearing refs from day one.

- **PR shape = 5 PRs as drafted** (PR0 refs migration → PR1 manifest → PR2 plan → PR3 code-gen → PR4 integration polish). Each lands independently in dependency order.
- **Code = first-class tier** (`code_*` with parent_id pointing at the approved plan). Standard four-state lifecycle. Approval triggers the git commit. Reviewable like other tiers.
