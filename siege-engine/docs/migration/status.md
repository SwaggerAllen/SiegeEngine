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

## Phase 4 — Deletion sweep ⏸ NARROWED, IN PROGRESS

See `docs/migration/deletion-inventory.md` for the punch list.

The original Phase 4 design assumed the deployed dashboard could
be fully repointed at `/siege/api/*` before the deletion sweep
ran. Reality:

- The siege server is **already deployed** as part of
  `backend/main.py` (mounted at `/siege`). No separate process.
- The skills + plugin work end-to-end against a local repo.
- The dashboard still calls legacy `/api/*` routes for **both**
  reads and writes — that's the live blocker.

The cleanup plan splits this into three loosely-coupled threads
(see `/root/.claude/plans/pure-crafting-marshmallow.md`):

1. **Phase A (this commit)**: doc reconciliation.
2. **Phase B**: frontend repoint of reads that have `/siege/api/*`
   equivalents (graph, structure summary, review summary, plan,
   batches, propagations, get-state, get-body).
3. **Phase C**: backend deletion of the per-tier generation/review
   stack (bootstrap routes, per-tier handlers, regen_context,
   websocket, tier-ops write endpoints, cli/manager). ~5-8K LOC.

**Deferred to a follow-up cleanup pass:** cohort / vocabulary /
reference / human-review-batch / pending-instruction-queue /
feedback-history backend modules. Their dashboard pages stay
functional against `/api/*` this round; their backend (~20K LOC
across models, alembic, reducer, pipeline, queries) stays alive.

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

1. **Phase B**: repoint the frontend's read paths at `/siege/api/*`.
   Smoke-test on the deployed dashboard against a sample project.
2. **Phase C**: drop the per-tier generation/review backend stack.
   Per-commit verification per the gate above.
3. **Future cleanup pass**: delete the deferred-feature backends
   (cohort / vocab / reference / review-batch / queue / feedback
   history) once the dashboard either drops those pages or grows
   v3 equivalents.
