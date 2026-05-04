# SiegeEngine — Claude Code session notes

Working notes for Claude Code sessions on this repo. Read this first
after resuming, then `git log --oneline -20` to catch up on recent
commits.

**Source of truth split.** The phase plan + per-phase status lives in
`docs/architecture/v2-roadmap.md`; the data model + meaning-engine
treatment lives in `docs/architecture/v2-rearchitecture.md`. This
file is operational only — verification commands, working patterns,
load-bearing invariants, durable decisions. Anything that reads like
"current progress" belongs in the roadmap, not here.

## Layout

Repo root: `/home/user/SiegeEngine`. The Python/JS project lives
under `/home/user/SiegeEngine/siege-engine/` — run all commands from
there unless noted. Backend is FastAPI + SQLAlchemy (SQLite, WAL)
under `backend/`; frontend is Vite + React + TypeScript + Zustand +
Tailwind under `frontend/`. All LLM calls go through the Claude CLI
subprocess (`backend/cli/manager.py`), not the Anthropic API directly.

Event-sourced model: every write goes through
`backend.graph.reducer.append_event`; projections (nodes, edges,
fragments, drafts) are derived from the event log.

## Verification commands

Run all of these from `siege-engine/` before claiming a change is
complete. Path gotchas matter — `ruff` / `mypy` live in `~/.local/bin/`,
not `.venv/bin/`, and mypy caches stale results aggressively.

```
# Backend
.venv/bin/python -m pytest tests/v2/ -q
ruff check backend tests && ruff format --check backend tests
rm -rf .mypy_cache && mypy backend

# Frontend (from siege-engine/frontend/)
npx vitest run
npx tsc -b --noEmit --force
npm run lint
npx vite build
```

Always nuke `.mypy_cache` before declaring mypy clean. Past sessions
hit this twice (`Component.kind` in Phase 3, `SubcomponentSummary.parent_id`
in Phase 4) where a stale cache masked a real type error. Use
`--force` on tsc to defeat its own stale-buildinfo cache.

## Development

```
# Backend
source siege-engine/.venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Frontend
cd siege-engine/frontend && npm run dev    # localhost:5173, proxies to :8000
```

Env vars use `SIEGE_` prefix (e.g. `SIEGE_ANTHROPIC_API_KEY`,
`SIEGE_JWT_SECRET_KEY`). See `backend/config.py` for the full list.

## Git conventions

- Develop on the per-session feature branch the harness assigns
  (visible via `git branch --show-current`). Never push to main
  without explicit permission.
- Commit messages: short first line, 2-4 line body explaining the
  why, trailing `https://claude.ai/code/session_...` link.
- Never `--no-verify` / `--amend` / force-push without being asked.
- Prefer adding files by name over `git add -A` when there's a risk
  of sweeping in unrelated state.

## Phase status

See `docs/architecture/v2-roadmap.md` for the live phase plan,
what's complete, and what's queued. This file deliberately doesn't
mirror that — phase status drifts faster than CLAUDE.md updates can
keep up with.

## V3-spec items out of v2 scope

Several items in the v3 platform spec are deliberately **not**
implemented in v2. If a future session touches one, flag it and
confirm the scope change is intended:

- Four non-scaffolding flows (feature-request, refactor, bug-fix,
  downward propagation, upward propagation)
- Bundle configuration system (platform spec §A.11)
- Phase-zero tier machinery
- `invokes:` primitive selector and the `downward_cascade` /
  `up_then_down` walk primitives
- `implicates_visit` edge mechanism
- `<assessment>` grammar for up-then-down flows
- Everything in the Part 3 core-platform-changes list
- Cross-project references (meta-design escape hatch)

## Thinking effort per tier (B6)

Top-of-chain tiers (feature expansion, requirements, sysarch)
plus comparch pass ``thinking_effort="max"`` to
``cli_manager.generate_with_usage``. The CLI manager forwards
that as ``CLAUDE_CODE_EFFORT_LEVEL=max`` on the single
subprocess invocation (scoped per-call via
``_build_subprocess_env``, not process-wide).

Comparch is on max because it carries the in-prompt
reconciliation pass (cross-section consistency, surface
closure, dep grounding, single-owner discipline,
rationale-not-inventory) — the cheaper way to fold that work
in without a separate reviewer round-trip is to pay for deeper
thinking on the existing generator turn. Per-comp cost shifts
into extraction-tier territory; revisit if budget pressure
shows up at scale.

The remaining propagation tiers (subcomparch, impl, fanin,
references, reviews) deliberately leave ``thinking_effort``
unset so ``CLI_MAX_BUDGET_USD`` isn't consumed by thinking
tokens before the real reasoning finishes. Handle quality
upstream is the investment that pays off downstream; the
late-stage compression tiers don't need deep thinking because
the handles they read are already the compressed form.

## Meaning-engine model

The generation chain is a meaning engine — each tier produces
compressed handles (names, roles, API intents, pubapi fragments)
that downstream tiers reason from directly. The chain alternates
compression, expansion, and rotation:

- **Feature expansion** — extraction from raw input
- **Requirements** — rotation (user-facing → system-level axis)
- **Sysarch** — compression (resps → components)
- **Comparch** — last compression before impl; carves a comp into
  subcomps and per-subcomp `<owns>` claims on the parent's resps +
  feat slices (multi-owner allowed; the same resp may be split
  across subcomps that each handle a different feat-slice). Replaces
  the retired subreqs tier — the scope-bounded expansion that used
  to live there folded into comparch's `<owns>` block.
- **Subcomparch** — leaf articulation, no more tiers to correct

Every prompt names its downstream reader, pushes against
category-speak, and frames the tier's transformation type.
Handle quality (meaning-per-token) is the load-bearing property —
if a tier's output is vague, the fix is in that tier's prompt,
not in passing more context downstream. The input doc only feeds
extraction tiers (expansion, reqs, sysarch); propagation tiers
(comparch, subcomparch, impl) work from handles only.

See `docs/architecture/v2-rearchitecture.md` §The system as a
meaning engine and `seed-docs/catapult-spec-v2.md` §A.3.1a for
the full treatment.

## Scheduling invariants

- **Presentational comparch gate**: a presentational comp's
  comparch waits until every one of its `domain_parent` targets
  has a populated `fanin_*` node. Helper:
  `queries.all_domain_parents_have_populated_fanin`. After the
  subreqs retirement, the unblock-on-fanin-commit walk in
  `fanin_generation._unblock_presentationals_on_fanin_commit` is
  the only path that re-enqueues a deferred presentational
  comparch — it fires after each fan-in content commit, so a
  presentational comp's comparch can run multiple times during
  bootstrap as its domain parents settle one by one.
- **Fan-in first-pass gate**: `on_impl_approved` only enqueues
  `v2.generate_fanin` when `all_impls_populated_for(owner)`
  returns true. Before first-pass, partial impl coverage leaves
  the gate closed. After first-pass, every approval re-fires
  (queue dedups on payload).
- **Reset compatibility**: clearing an impl's content via a
  per-tier force-reset flips the gate closed until re-approved.

## Tree view status model

The sidebar tree's dot badges mirror a node's real state:

- **Pulsing amber** — generation running (queued or running job)
- **Red** — latest generation job failed (`has_error`)
- **Amber** — pending draft awaiting review (`has_pending_draft`)
- **Blue** — prereqs met but idle / needs user kick
  (`needs_user_action`): latest job cancelled, or tier is ready
  to generate but hasn't been triggered (typically `impl`, or
  any tier post-cancel)
- **Green** — approved content landed (`has_content` and no
  other badge applies)
- **No dot** — upstream-blocked (prereqs not satisfied;
  waiting on the chain, not the user)

Descendant rollups emit dimmed mini-dots on collapsed ancestors
so hidden state stays visible.

The tree's pulsing-amber state spans **both** draft generation
and AI self-review generation — `running.py`'s `_TIER_JOB_TYPES`
includes the 8 `v2.review_<tier>` job types, so a draft that
committed but is still being reviewed reads as "generating" in
the sidebar. The pulse only flips off once the review job
terminates (succeeded or failed).

## AI self-review

Every approved tier has a second LLM pass that critiques the
generator's output. Reviews are advisory — approving a draft
doesn't wait on review completion — and are **automatic** after
every draft commit (gated off only by `SIEGE_DISABLE_AI_REVIEW=1`,
which the chain integration test sets so it doesn't double its
CLI call count).

- **Per-tier module triad.** Every reviewed tier has three
  matching modules: `review_context/<tier>.py` (the context
  gatherer that **both** the generator and the reviewer call so
  they see identical input), `prompts/review/<tier>.py` (the
  review prompt), and `handlers/review_<tier>.py` (the job
  handler registered as `v2.review_<tier>`). A shared
  `prompts/review/_shared.py` template + `_tier_review.py`
  wrapper keep the per-tier boilerplate to a couple dozen lines.
- **Storage.** `Draft.review_text` holds the review output for
  draft-based tiers; `Node.review_text` holds it for fan-in
  (which writes content directly to the node without a draft
  cycle). `DraftReviewUpdated` event routes by
  `target_type="draft" | "node"` and the reducer writes to the
  right row.
- **Prompt contract.** One XML response, parsed via
  `backend/graph/parsers/review_xml.py` into a `ParsedReview`
  dataclass. Schema:

  ```xml
  <review>
    <intro>One or two short paragraphs (3–6 sentences total)
  giving a "how close to finished" read on the artifact. Display-
  only — does not feed the regen loop.</intro>
    <score>0</score>  <!-- integer 0–100 -->
    <handles-structure>
      <finding id="h1">…</finding>
      …
    </handles-structure>
    <architectural-decisions>
      <finding id="a1">…</finding>
      …
    </architectural-decisions>
  </review>
  ```

  Both `<intro>` and `<score>` are required. Score buckets are
  0–30 (fundamental rework), 31–60 (structural fixes), 61–85
  (minor refinements), 86–100 (ready). Each section's findings
  are individually-addressable so the frontend can offer
  selective apply-as-feedback later. On tiers that don't make
  tech decisions — expansion, requirements, fan-in — the
  `<architectural-decisions>` section critiques the
  decomposition axis instead.
- **Frontend render states.** `BootstrapDraftPanel` and
  `FanInPanel` both show a review block with four states keyed
  off `review_status`:
  - `idle` + non-empty `review_text` → collapsible "AI Review"
    markdown (default collapsed)
  - `running` → spinner + "Reviewing… attempt N/M"
  - `failed` → red banner showing `review_last_error` +
    "Retry review" button (wired to the per-tier
    `/review/retry` endpoint)
  - `idle` + empty `review_text` → hidden (pre-Phase-8 drafts
    and reviews-disabled mode)
- **Independent retry loop.** The review handler reuses
  `_record_attempt_progress` for transient-CLI retries, so the
  frontend gets a live attempt counter independent of the
  generator's counter. Hard failures surface as
  `review_status="failed"` + `review_last_error`.
- **Regen / reset cancels in-flight reviews.**
  `persist_draft`'s prior-draft-discard block cancels the stale
  draft's review; fan-in reset cancels its node-scoped review.
  The new draft / node starts with `review_text=""`.

## Tier-ops dashboards

The Tier Operations sidebar entry (`:tier-ops`) hosts per-tier
bulk operations + a read-only review-summary dashboard:

- **Reset All** — destructive sweep of every node in the tier
  with confirm-tap. Wraps the per-node `bootstrap_reset` with
  `force=True` so the approval gate is bypassed.
- **Regen From Reviews** — fans the per-node "Reject &
  Regenerate" action across every pending-draft scope in the
  tier. Wraps `bootstrap_feedback("")` per scope: each pending
  draft's AI review rides forward as `prior_review_text` on the
  regen, the stale review row is cleared, in-flight review jobs
  for the discarded draft are cancelled, and a fresh generation
  is enqueued. The post-commit hook on the new draft fires the
  next AI review automatically — no separate review enqueue.
  Approved-only scopes 409-skip and report in the result line;
  use Reset All for those.
- **Review summary** (`GET /projects/:id/tiers/:tier/review-summary`)
  — aggregates parsed `<review>` blocks across the tier into
  score min/mean/median/max, a 4-bucket histogram, and a
  copy-paste-ready markdown block of per-scope intros ordered
  worst-first. Backed by `backend/graph/review_summary.py`;
  rendered by `TierReviewSummaryPanel` inline beneath each row.
  The panel has a worst-N slider + score-threshold filter so the
  iteration loop on a multi-comp project stays scoped.

The registry that drives all three is
`backend.graph.tier_ops_routes._registry()` — adding a new tier
to any of these dashboards is a one-line entry there.

The dashboard also exposes a **Structure summary** panel per
tier — per-node metrics + tier-level aggregates (counts,
distributions, kind/foundation ratios, multi-owner prevalence,
content-presence). Backed by `backend/graph/tier_structure.py`;
GET endpoint at
`/projects/:id/tiers/:tier/structure-summary`. Eight tiers
covered (the six BootstrapTierConfig tiers plus `fanin` and
`references` in a separate read-only section). The frontend
panel renders generically off the `{per_node, aggregate}`
shape — table columns derive from the first row's metric keys;
no per-tier rendering code.

## Batches (universal operation tagging)

Every multi-job tier-op (Reset All, Regen From Reviews, Resume
Tier) and every per-node operation (`bootstrap_reset`,
`bootstrap_feedback`, `bootstrap_approve`, single review retry,
lazy-bootstrap on first GET) mints a row in the **`batches`**
table at the top of the route. The minted `batch_id` then
threads through:

- `Job.batch_id` — every job the operation enqueues.
- `Job.payload["batch_id"]` — same id, for handlers that need
  to read it without a Job lookup.
- `Draft.batch_id` — the existing per-draft column, now sourced
  from the running Job's payload-batch by
  `_resolve_draft_batch_id` in `_bootstrap_generation.py`. So
  multi-draft tier-ops collapse onto **one** Draft.batch_id
  shared across every draft they produce, instead of one fresh
  per-draft uuid. Falls back to a fresh mint only for
  pre-Phase-14 queued jobs and for system-side cascade
  enqueues that didn't carry a batch.

What this unlocks:

- **Resume by gap-fill.** The
  `POST /projects/:id/batches/:batch_id/resume` endpoint walks
  the batch's jobs and re-enqueues only the ones whose status
  is not `completed`. Completed work stays put — the principle
  is "fill the gaps, don't throw out partial data". Re-enqueued
  jobs carry the same `batch_id` so the operation stays a
  single logical unit even across restarts.
- **Review-summary scoping by batch.** The review-summary
  endpoint accepts `?batch_id=<id>` and filters per-scope draft
  lookup to drafts whose `Draft.batch_id` matches. Lets the
  user scope an iteration cycle's review aggregation to the
  drafts that came out of one Reset All / cohort generation /
  etc., not the full corpus.
- **Per-node ops are batch-tagged too.** A single-node
  `bootstrap_feedback` mints `op_type="single_node_feedback"`
  with one entry in `scope_keys`; this eliminates the "is this
  code path one of the ones with a batch_id?" check across
  downstream consumers.

The mint helper lives in `backend.graph.batches.mint_batch`;
helper queries (`gaps_in_batch`, `jobs_in_batch`,
`list_batches_for_tier`) are in the same module. Distinct from
`ReviewBatch` in `backend/models/review.py` — that's the older
human-curated review-session concept; the new `Batch` model
records every issued operation, including single-node ones.

## Cohorts (sampling campaigns)

Saved selections of comp IDs that drive iteration campaigns at
the next tier down. The intended workflow when iterating a
prompt:

1. Open the comparch structure summary, hit "Select for cohort",
   either auto-suggest (stratified greedy sampler against
   per-tier axis weights) or hand-pick comps, save as a cohort.
   `cohort.comp_ids` always holds top-level comp IDs (the units);
   `cohort.tier` records which generator the cohort drives.
2. Each iteration cycle: kick off cohort regenerate from the
   Cohorts page. Two modes:
   - **review** (`bootstrap_feedback("", force=True)` per scope) —
     keeps approved content, threads `prior_review_text` forward
     so the model iterates on its own critique.
   - **fresh** (`bootstrap_reset(force=True)` per scope) — wipes
     content + downstream cascade, generates from scratch with
     no prior context.
3. Add an exploration sample each cycle
   (`/tiers/:tier/exploration-sample`) — picks N comps not in
   the canonical cohort and not in any prior same-tier
   exploration batch, regenerates at the chosen tier. Surfaces
   pattern-level findings the canonical sample can't see.
4. After scores plateau, fire the full-corpus action
   (`/tiers/:tier/full-corpus`) once to cover the long tail.
5. Cycle history view (per-cohort, in `CohortsPanel`) lists
   prior `cohort_regenerate` batches with mode badge, mean
   score, and per-mode-pair score deltas (fresh vs prior fresh,
   review vs prior review — cross-mode batches show stats but
   no delta arrow because the baselines aren't comparable).

**Same-tier scope walk.** Cohort regenerate, exploration-sample,
and full-corpus all use the shared `scope_ids_from_comp` helper
in `tier_ops_routes.py` to translate "top-level comp ID + target
tier" into scope tuples for the BootstrapTierConfig:

- target=`comparch` → `[(comp_id,)]` (no walk, runs comparch on
  the comp directly).
- target=`subcomparch` → `[(sub_id,) per sub child]` (walks one
  level into the comp's subs).
- target=`impl` → not implemented yet (raises 501).

The exploration-sample exclusion pool is tier-scoped: filtering
by `Batch.tier == target_tier` so a comparch exploration sample
doesn't pollute a later subcomparch sample's exclusion set.

The frontend `CohortsPanel` reads the active cohort's tier and
threads it through every campaign action call; only one
"campaign tier" is active at a time, derived from the active
cohort. `COHORT_SELECTABLE_TIERS` in `TierStructureSummaryPanel`
gates which structure-summary tiers can save cohorts (today:
comparch only).

Sampler axis weights live in the `cohort_sampler_configs` table
— per `(project, tier)` JSON config editable via the
`/sampler-configs/:tier` GET/PUT endpoint or the inline
`SamplerConfigEditor` UI on the cohorts page. Defaults seeded on
first read for the comparch tier (kind / foundation / resp_count
/ dep_count / inbound_dep_count, with `resp_count` weighted highest
as the dominant complexity signal). Tuning weights doesn't require
a deploy — important so axis edits don't interrupt in-flight
generations.

**Upstream-only axes rule.** Sampler axes for iterating tier T
must be computed from sources upstream of T, never from T's own
outputs. At cohort selection time the target tier hasn't run yet,
so any axis derived from its outputs collapses to a single bucket
across every candidate and the sampler degenerates to alphabetical
fill. The original comparch defaults violated this on `sub_count`
and `multi_owner_resp_count` (both are comparch outputs); they
were dropped from comparch and belong on a future subcomparch
default config where they're upstream signals. Apply the same test
when adding axes for any new tier: would this metric exist on a
candidate that has never been generated?

The cohort regenerate path uses `bootstrap_feedback`'s
`force=True` parameter to bypass the `has_been_approved` 409 —
per-node UI buttons stay gated by default, only campaign
operations push regen through approved nodes.

Subcomparch's tier-op scope tuples are 1-element `(sub_id,)`
because `SUBCOMPARCH_CONFIG.get_node` is `_get_sub_node(db,
project_id, sub_id)`. This was a pre-existing inconsistency
(2-tuples in `_subcomp_scope` would have crashed Reset All on
subcomparch); fixed during Phase 3b along with the new
endpoints.

## Frontend patterns

- **All Zustand stores use `createSafeStore`** (`frontend/src/store/createSafeStore.ts`)
  instead of bare `create()`. Middleware catches async action
  errors and logs to `errorLogStore`. Fire-and-forget store
  calls can't produce unhandled rejections. The `errorLogStore`
  itself uses bare `create()` to avoid circular deps.
- **Always use selectors on Zustand stores**:
  `const value = useStore((s) => s.field)`, never bare
  `const { a, b } = useStore()`. Bare calls subscribe to the
  entire store and cause render storms (especially with
  high-frequency updates like SSE events).
- **Safe hook wrappers** (`hooks/useSafe.ts`): `useSafeEffect`,
  `useSafeMemo`, `useSafeCallback` catch errors that React's
  error boundaries miss (effects, memos, callbacks) and log
  them to `errorLogStore`.
- **Test mocks** that stub a Zustand store must accept the
  selector function: `vi.fn((selector) => selector ? selector(state) : state)`.
- **Conditional polling for live attempt counters**: per-tier
  detail hooks use `runningRefetchInterval` from
  `hooks/useBootstrapHooks.ts` — polls every 2s while
  `generation_status === 'running'` so the attempt counter
  stays fresh (SSE drives event-based refetches; the Job-row
  payload carrying `_current_attempt` doesn't produce events).

## Known design debt (not urgent, worth tracking)

- **Topological dispatch within a parent comp's subcomparch batch.**
  Currently the comparch_mint fan-out enqueues
  `v2.generate_subcomparch` for every minted subcomponent at once,
  and the worker processes them in FIFO order. Subs that generate
  early see skeletal pubapis for their siblings; later-generating
  subs see richer context. Works fine for MVP but is a quality
  optimization for later.
- **Mint handler idempotency for node-creating tiers.** The
  reducer idempotency fix (`92a0f8f`) made `FragmentUpdated` and
  `EdgeCreated` safely re-applicable, which covers
  `subcomparch_mint` completely. But `comparch_mint`,
  `sysarch_mint`, `feature_mint`, etc. still create new nodes with
  fresh IDs on each run, so they need their own "already minted"
  guard checks. Those guards exist today and work; just noting the
  reducer-level fix doesn't solve the node case by itself.
- **Frontend/backend contract drift.** Zod schemas on the frontend
  and Pydantic models on the backend are written by hand. Two
  type errors have slipped through before — would benefit from a
  generated or checked contract layer. Low priority.
- **Worker loop concurrency.** Handler tests call handlers
  directly; the real worker-loop polling / locking / retry path
  is only exercised by `tests/v2/test_full_bootstrap_chain.py`
  in a single-threaded drain variant. No concurrency test
  exists for the real loop.
- **Phase 4 alias scheme stays.** Phase 5 subcomparch uses real
  `comp_*` IDs throughout (`a85f5f2`), but Phase 4 comparch and
  Phase 3 sysarch still use the alias scheme in `<subcomponents>`
  / `<sub-dependencies>` and `<components>` / `<dependencies>`.
  This is deliberate — those tiers declare brand-new entities
  that don't have IDs yet at generation time, and pre-minting IDs
  would shift complexity rather than remove it.
- **Force-reset job cancellation is project-wide.** Per-comp
  resets cancel every in-flight downstream-tier job in the
  project, not just jobs scoped to the target comp. Aggressive
  but consistent with the "force" framing; scope-aware
  cancellation is a follow-up if/when someone hits it in practice.

## Seed document

The project dogfoods itself — the input document for the primary
dev project is SiegeEngine's own architecture. There's an open
thread to replace this with a real-world catapult spec so
dogfooding exercises more representative input shapes; that's a
content task the user wants to workshop interactively rather than
delegating. Not a code change.

## Things to not relitigate

- **Structured edit UIs: graph primary, list a11y fallback.** UIs
  #3 / #5 / #6 are graph-first via the shared `EditableGraph`
  wrapper; the `Graph | List` toggle exposes a list view as the
  accessibility fallback, not as a parallel product. Don't add
  list-only affordances the graph view can't reach, and don't
  add graph-only affordances that break the list fallback.
- **Playwright / full browser E2E** is deferred until the UI
  stops churning. The full bootstrap chain integration test gets
  most of the value at 5% of the maintenance cost.
- **Drag-to-connect on graph editors.** HTML5 pointer-event drag
  on Cytoscape nodes is flaky — flaky enough that two-tap is the
  working pattern on both desktop and touch. Don't try to
  reintroduce drag semantics; if someone wants a visual
  "connecting" affordance during the two-tap, draw a ghost edge
  from the selected-source instead.
- **Node drag-repositioning against ELK.** ELK is authoritative
  for layout on every graph editor. Users adjusting positions
  manually fights the layout engine and the adjustments don't
  persist through re-layouts.
- **Subreqs tier was retired.** Comparch carries the parent-resp +
  feat-slice ownership picture directly via per-subcomp `<owns>`
  blocks; legacy subreqs nodes (`tier="subreqs"`, `tier="resp"`
  with `parent_id != None`) may linger in pre-retirement
  projections but are filtered out of the structure projection
  and the nav tree. Don't reintroduce a separate subreqs tier.

## Deployment

- **Fly.io**: deploys from `siege-engine/fly.toml`, region `iad`.
- **CD**: `.github/workflows/deploy.yml` — deploys on push to
  `main` via `flyctl deploy --remote-only`.
- **CI**: `.github/workflows/ci.yml` runs on PRs only (frontend
  typecheck/test/build, backend lint/typecheck/test). CI and
  deploy are decoupled — merging to main triggers deploy
  regardless of CI.
