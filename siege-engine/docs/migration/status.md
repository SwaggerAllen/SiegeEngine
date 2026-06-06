# Migration status (snapshot)

Branch: `claude/fix-queue-job-ordering-pzz20`

The full plan lives outside the repo at
`/root/.claude/plans/pure-crafting-marshmallow.md`. This file is the
in-repo snapshot of what's landed and what's pending so future
sessions can orient without re-reading the planning conversation.

## Phase 0 — Schema freeze + plugin scaffold ✅ LANDED

- `docs/migration/state-schema.md` — state JSON schema v1 + path
  layout + batches/cohorts + idempotency
- `docs/migration/mcp-surface.md` — initial tool surface sketch
  (historical: the MCP transport was later dropped — see step 5 below;
  the read endpoints survive as `siege.server.app`'s HTTP routes)
- `.claude-plugin/plugin.json` — manifest
- `.claude-plugin/skills/draft-feature-expansion/SKILL.md` — initial
  stub (regenerated from template in Phases 1+2)

## Phase 1 — Bootstrap vertical substrate ✅ LANDED

`siege-engine/siege/` — full Python package.

- `state.py` — typed state JSON with load / dump / sha256 / nonce
- `git_view.py` — per-(project, ref, head_sha) snapshot with
  fetch-debounced clone wrapper and lazy body loading
- `fragments.py` — `FragmentKind` enum ported verbatim + new
  body-section parser
- `parsers/{xml_sections,review_xml}.py` — ported verbatim
- `projection/` (formerly `tiers/`) — generation + review context
  readers for all tiers; see step 5 below for the refactor that
  formalized this package boundary
- `validate.py` — pre-commit validation gate
- `server.py` — FastAPI app with `/api/*` HTTP routes (no `/mcp` —
  see step 5)
- `auth.py` — simplified JWT (ported from `backend/auth/service.py`)
- `cli.py` — writer-side CLI; the bulk of the v3 write surface
- `tests/` — covers state round-trip, body section parse, review
  XML parse, scope paths, validate gate, CLI write paths, drift
  repair, batch mint, sub-tier paths.

### Prompt port (extra, landed after substrate)

The static instruction text from every old `backend/graph/prompts/*.py`
module is extracted verbatim into `siege/prompts/<tier>.md` (and
the reviewer-architecture critique block into `review_<tier>.md`). Per-
tier readers attach the appropriate prompt under `instructions` /
`review_instructions` keys on the bundle so skills don't have to know
where the prompt lives.

### Deployment mount (landed after substrate)

`backend/main.py` mounts `siege.server.app` at `/siege`. The new
read-only surface ships alongside the legacy write surface during
the migration. After the per-tier deletion lands (see Phase 4
below), the rest of `backend/` continues serving project CRUD +
auth + the deferred-feature panels.

## Phase 2 — Downstream tiers ✅ LANDED

The substrate already covers all 7 tiers — Phase 1 and Phase 2 share
the same `siege/projection/` directory because the per-tier reader
pattern was uniform enough that splitting them into separate phases
of work was artificial. The bootstrap-vs-downstream distinction lives
in the slash commands (`/scaffold` is upstream-only, `/run_tier`
handles any tier).

`.claude-plugin/`:

- `skills/` — initial per-tier and shared skills (draft / review /
  regen-with-feedback × 7 tiers + mark-drafted, mark-reviewed,
  mark-approved, repair-state-drift). Authoring skills landed later;
  see "Authoring skill suite" below.
- `agents/` — per-tier generator subagents for fan-out
- `commands/` — `/scaffold`, `/run_tier`, `/regen_below`,
  `/continue`, `/status`

Per-tier skills reference the writer CLI inline so the steps the
skill takes are concrete (not abstract pseudocode).

## Phase 3 — Frontend retarget ✅ LANDED

- **Deleted**: `api/jobs.ts`, `GenerationQueuePanel`,
  `QueueAnnounce`, `QueuePanel`, `useProjectEventStream`,
  `useQueueQueries`, plus their tests.
- **SSE mount** stripped from `ProjectWorkspacePage`.
  `runningRefetchInterval` neutered to a no-op.
- **Branch selector**: new `BranchSelector` + `RefProvider` +
  `useSelectedRef` context wired into the workspace header;
  persists per-project to localStorage.
- **Action-surface cuts**: Approve / Reject / Reset / Retry / Stop
  flows removed from `BootstrapDraftPanel`, `TierOpsPanel`,
  `CohortsPanel`, `FanInPanel`. Replaced with disabled "Open in
  CC" buttons + TODO comments naming the equivalent skill.
- **API annotations**: `FUTURE:` headers on read API modules
  pointing at the future siege endpoints.
- **Cheat sheet page** at `/cheatsheet` (unauthenticated, markdown
  bundled into the build via Vite `?raw`).
- **Dev token panel** at the top of the cheat sheet — shows the
  logged-in user's JWT in copy-paste-ready `export SIEGE_TOKEN=…`
  form with expiry + relative time.

Carry-overs (`api/queue.ts` + `useQueueMutations`) kept as
doomed shims pending the dashboard repoint (see Phase 4 below)
because editor panels still pull `Instruction` types and
`mintClientId` from them.

### Deploy + on-ramp (extra, landed after Phase 3)

- **Dockerfile** picks up `siege/` + `scripts/` so the mounted
  app + bootstrap script reach the runtime container.
- **CI workflow** lints + typechecks `siege/` alongside `backend/`.
- **Plugin manifest** points at the real droplet hostname.
- **Bootstrap script** at `scripts/siege-bootstrap.sh` served at
  `https://siege.strutco.io/bootstrap.sh` (top-level route in
  `backend/main.py` registered before the SPA catch-all — fixed
  a 200/blank-html bug where the SPA was swallowing the request).
  Pinned by `tests/v2/test_bootstrap_routing.py`. Mirrors plugin
  contents into target project repos for mobile CC compatibility.
- **CLAUDE.md** updated: Deployment section rewritten (was stale
  Fly.io copy); new "Architecture: v3" and "Cheat sheet" sections.

## Step 4 — Schema v2 (phased impl + fanin) ✅ LANDED

`PHASED_TIERS = {"impl", "fanin"}`, the `phase` dimension on `Scope`,
`schema_version=2` files for phased nodes, the per-phase on-disk
layout (`state/impl/<parent>/p<N>/<sub>.json`,
`impl/<parent>/subs/<sub>/p<N>/body.md`). Tolerant parsing of pre-
phasing (v1) files. Covered by `siege/tests/test_state_v2.py`.

## Step 5 — Projection refactor + MCP transport dropped ✅ LANDED

`siege/tiers/` → `siege/projection/`. The per-tier readers split
into a shared `_base.py` (~270 lines) + seven ~80-line per-tier
modules. Five whole-project projections (graph, plan, structure
summary, review summary, fragments) sit alongside.

The `/mcp` (JSON-RPC) transport was **dropped** during this step.
`siege/server.py` exposes only the `/api/*` HTTP route surface (15
read endpoints — see `grep "@app" siege/server.py`). The migration
had assumed an MCP server in the generate loop; it turns out the
skills run the `siege` CLI locally on the project repo and never
need a remote tool surface. The deployed server's job is the
dashboard read API, full stop.

## Step 6 — Write CLI completion ✅ LANDED

`siege/cli.py` carries the full v3 write surface. Subcommands:

- `write-draft` / `write-review` / `write-approval` — the
  draft → review → approve lifecycle
- `mark-drafted` — re-sync state to a hand-edited body
- `repair-drift` — recompute body_sha256 fields
- `mint-batch` / `mint-nonce` — id minting
- `mint-plan` — materialize phased impl stubs from
  `state/plan.json` (gains `--dry-run` in step 7)
- `get-state` / `get-context` / `get-review-context` —
  read-projection
- `compute-plan` / `get-structure-summary` / `get-review-summary`
- `get-project-graph` — full DAG
- `list-batches` / `list-scopes`

`get-context` gained `--prompt-variant {default,modify}` so
`/modify_*` skills swap the bundle's `instructions` field.

## Step 7 — Propagation primitive ✅ LANDED

`siege/propagation.py` — `Propagation` records under
`state/propagations/<id>.json`. Worklist primitive with per-entry
`(scope, status, note)` triples, four statuses (pending /
in_progress / done / skipped), rolled-up record status, `update_entry`
+ `add_entries` mutation helpers. CLI subcommands:

- `open-propagation` — materialize a record from a worklist
- `update-propagation-entry` — flip one entry's status
- `compute-downstream` — preview the top-down worklist
- `list-propagations`
- `open-propagation --from-source-scope-json` — top-down walk
  shortcut (one entry per existing downstream scope, walking
  `feature_expansion → requirements → sysarch → comparch →
  subcomparch → impl`; fanin skipped, bottom-up)
- `open-propagation --from-plan-change` — diff the plan projection
  against existing impl state files; emit pending entries for
  impls whose closure changed + skipped entries for impls dropped
  by the new plan

Skill: `/propagate_downstream` drives an open propagation.

## Step 8 — Authoring skill suite ✅ LANDED

11 new skills + 3 new prompts, all manual-propagate (the skill
commits the artifact change and echoes a `/propagate_downstream`
hint; nothing auto-opens).

**Substrate edits (mechanical, no LLM):**

- `add-feature` / `remove-feature` — append / delete `<feature>`
  blocks in `feature_expansion/proj/body.md`
- `add-responsibility` / `remove-responsibility` — same for
  `requirements/proj/body.md`. Remove ops accept `--feat-id` /
  `--resp-id` (ledger lookup) or `--name` (body match).

**Modify-\* (LLM-driven, surgical):**

- `modify-sysarch` / `modify-comparch` / `modify-subcomparch` —
  same wrapper as the regen-with-feedback skills but with a
  "preserve, don't redesign" prompt variant
  (`siege/prompts/modify_<tier>.md`). Components, deps, and
  sections the feedback doesn't touch round-trip verbatim.

**Phase registry (mechanical):**

- `add-phase` / `remove-phase` — CRUD on
  `state/phases/<phase_id>.json`
- `assign-feature-to-phase` / `unassign-feature-from-phase` —
  edit a phase's `feature_ids` list. Assign strips the feat from
  any prior phase first (one-phase-per-feature invariant).

## Phase 4 — Deletion sweep ✅ LARGELY LANDED

See `docs/migration/deletion-inventory.md` for the original punch
list. The bulk of Phase 4 landed across this branch — the
dashboard's per-tier panels read from the substrate via siege, and
the legacy backend's per-tier surface (handlers, routes,
dashboards, supporting modules) is gone.

**Frontend (read repoint + dead-code removal):**

- Siege `get_body` extended with `which='draft'|'review'` so the
  read-only panels render both sides through one endpoint.
- New `useScopeState` hook stitches `/get-state` + `/get-body` ×2
  with conditional fetching.
- 8 per-tier panels (RequirementsPanel / SysarchPanel /
  FeatureExpansionPanel / ComparchPanel / SubcomparchPanel /
  ImplPanel / FanInPanel + the shared BootstrapDraftPanel shell)
  rewritten as v3 read-only views: status chip + draft body in
  `<pre>` + review body when present + "Open in CC" skill-hint
  footer. ~1500 LOC removed from these panels alone.
- Dead frontend exports gone: 7 per-tier mutation hooks, 6
  per-tier query hooks, 6 per-tier api modules, and their tests.

**Backend (per-tier generation / review / mint / route deletion):**

- 7 per-tier generation handlers + 5 mint handlers + 7 review
  handlers + 2 policy-application handlers — all gone.
- `_tier_review.py`, `_bootstrap_review.py`, `_readiness.py`,
  `review_context/*`, `prompts/review/*`, `prompts/<tier>.py`,
  `regen_context.py` (1.5K LOC), `expansion.py` / `requirements.py`
  / `sysarch.py`, `per_comp_reset.py` — all gone.
- `tier_ops_routes.py` (Reset All / Regen From Reviews / etc.),
  `cohort_routes.py`, `cohort_sampler.py`, `tier_structure.py`,
  `review_summary.py` — all gone. Their router mounts came out of
  `backend/main.py`.
- `backend/graph/routes.py` shrunk from 4195 → 1700 LOC: every
  per-tier endpoint block (EXPANSION/REQUIREMENTS/SYSARCH/
  COMPARCH/SUBCOMPARCH/IMPL/FANIN configs + prompt-preview +
  reset + review-retry + cancel) deleted.
- `bootstrap_routes.py` slimmed from 996 → 689 LOC: dropped
  `bootstrap_retry_review`, `wipe_node`, `bootstrap_reset`,
  `bootstrap_prompt_preview`.
- `backend/graph/__init__.py` drops 17 handler registrations;
  only `rename_rewrite`, `expand_single_feature`, and
  `generate_reference` survive alongside `apply_instructions`.
- `backend/graph/running.py` rewritten as a refs-only
  tracker — non-ref tier nodes don't get
  generation_running/has_error badges anymore (the dashboard
  is read-only for them).
- `backend/projects/service.py` drops the auto-enqueue-on-create
  path; new projects land with input doc and stop. Users kick off
  generation via CC skills.
- ~40 test files for the deleted per-tier surface — gone.

**Refs + vocab preservation pass — DONE:**

- v3 git-backed routes (`references_git_routes.py` +
  `vocabulary_git_routes.py`) handle all writes. Bodies live in
  the project repo at `refs/<ref_id>/body.md` and
  `vocab/<vocab_id>/body.md`; the server records git coordinates
  and never calls the LLM.
- `siege.cli create-ref` / `create-vocab` write the body file,
  commit, push, and POST to register. Skills (`/create_ref`,
  `/create_vocab`) shell out to the CLI.
- Dashboard refs + vocab UI went read-only: `CreateReferenceDialog`
  / `CreateVocabEntryDialog` deleted, panels rewritten without
  mutation hooks, write methods stripped from
  `api/references.ts` + `api/vocabulary.ts`.
- Backend retirement: deleted `bootstrap_routes.py`,
  `handlers/generate_reference.py`, `handlers/_tier_generation.py`,
  `handlers/_bootstrap_generation.py`, `prompts/reference.py`,
  `running.py`. Trimmed `routes.py` from 1806 → 1024 LOC (all
  legacy ref/vocab write endpoints + `REFERENCE_CONFIG` removed).
  Slimmed `references.py` + `vocabulary.py` to simple lookups
  (LLM-prompt rendering helpers gone — context now built in the
  v3 projection layer).
- `fanout.py` drops the `tier == "ref"` regen-enqueue branch.
  `backend/graph/__init__.py` no longer registers
  `generate_reference`.
- `pipeline/queue.py` drops the `TierDeferredError` handling +
  `_complete_deferred_job_sync` (only used by `_tier_generation`).

**What still stands:**

- `backend/graph/handlers/{expand_single_feature,rename_rewrite}.py` —
  used by the apply-instruction (pending-edit) flow.
- `backend/cli/manager.py` + `backend/pipeline/` — still needed by
  apply-instruction.
- Legacy persistence layer (SQLAlchemy + alembic + models) —
  untouched.

## Phase 5 — Optional polish ⏸ NOT STARTED

Deferred per plan:

- Merge-conflict retry on push (multi-writer)
- Repair skills beyond `repair-state-drift`
- CI validators running `verify_dep_graph(ref)` on PRs

## Verification commands

```
# Backend
cd siege-engine
.venv/bin/python -m pytest tests/v2/ siege/tests/ -q
~/.local/bin/ruff check siege backend tests scripts && \
  ~/.local/bin/ruff format --check siege backend tests scripts
rm -rf .mypy_cache && ~/.local/bin/mypy siege backend

# Frontend (from siege-engine/frontend/)
npx vitest run
npx tsc -b --noEmit --force
npm run lint
npx vite build
```

## Next gates (in order)

1. **Final backend shrink**: delete the apply-instruction /
   pending-edit machinery if the dashboard's feature-proposal
   flow follows refs to CC skills; delete the matching
   feature-expansion + rename-rewrite handlers; delete
   `backend/cli/`, `backend/pipeline/`.
2. **Persistence retirement** (last): drop the SQLAlchemy
   projections, alembic migrations, websocket, and the rest of
   the SQL backend once no surviving endpoint reads or writes
   them. End state matches `docs/migration/deletion-inventory.md`'s
   "what survives" section.
