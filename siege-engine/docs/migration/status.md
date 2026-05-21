# Migration status (snapshot, 2026-05-18)

Branch: `claude/fix-queue-job-ordering-pzz20`

The full plan lives outside the repo at
`/root/.claude/plans/pure-crafting-marshmallow.md`. This file is the
in-repo snapshot of what's landed and what's pending so future
sessions can orient without re-reading the planning conversation.

## Phase 0 — Schema freeze + plugin scaffold ✅ LANDED

- `docs/migration/state-schema.md` — state JSON schema v1 + path
  layout + batches/cohorts + idempotency
- `docs/migration/mcp-surface.md` — read-only tool surface
- `.claude-plugin/plugin.json` — manifest pointing at the (not-yet-
  deployed) MCP server URL
- `.claude-plugin/skills/draft-feature-expansion/SKILL.md` — initial
  stub (regenerated from template in Phases 1+2)

Gate not yet passed: the plugin install + MCP transport need to be
verified on mobile CC. That's a real-world test, not a unit test.

## Phase 1 — Bootstrap vertical substrate ✅ LANDED (code, not validated)

`siege-engine/siege/` — full Python package, 16/16 smoke tests
pass, ruff clean, ruff format clean.

- `state.py` — typed state JSON with load / dump / sha256 / nonce
- `git_view.py` — per-(project, ref, head_sha) snapshot with
  fetch-debounced clone wrapper and lazy body loading
- `fragments.py` — `FragmentKind` enum ported verbatim + new
  body-section parser
- `parsers/{xml_sections,review_xml}.py` — ported verbatim
- `tiers/_base.py` + 7 per-tier modules — generation + review
  context readers for all tiers
- `review_summary.py` + `structure.py` — aggregations matching
  the existing frontend panels' shape
- `validate.py` — pre-commit validation gate (cheap section-presence
  check; the 4K-line per-tier validators from
  `backend/graph/parsers/validators.py` aren't yet ported)
- `tools.py` — MCP tool functions (9 read tools)
- `server.py` — FastAPI app with `/api/*` (HTTP) + `/mcp` (JSON-RPC)
  transports against the same tool surface, bearer JWT auth
- `auth.py` — simplified JWT (ported from `backend/auth/service.py`)
- `cli.py` — writer-side CLI: `write-draft` / `write-review` /
  `write-approval` / `repair-drift` / `mint-batch` / `mint-nonce`.
  Skills invoke this via Bash to materialize state JSON without
  hand-writing it.
- `tests/test_smoke.py` + `test_cli.py` — 16 tests covering state
  round-trip, body section parse, review XML parse, scope paths,
  validate gate, CLI write paths (draft → review → approval),
  drift repair, batch mint, sub-tier paths.

### Prompt port (extra, landed after substrate)

The static instruction text from every old `backend/graph/prompts/*.py`
module is extracted verbatim into `siege/prompts/<tier>.md` (and
the reviewer-architecture critique block into `review_<tier>.md`). Per-
tier readers attach the appropriate prompt under `instructions` /
`review_instructions` keys on the bundle so skills don't have to know
where the prompt lives. 14 prompt files total, sizes range from 365B
(review_fanin) to 45KB (sysarch).

### Deployment mount (landed after substrate)

`backend/main.py` mounts `siege.server.app` at `/siege_mcp`. The
new read-only surface ships alongside the old write surface during
the migration. After Phase 4 deletion the mount moves to `/` and
`backend/main.py` shrinks to project CRUD + auth login. `pyproject.toml`
now includes `siege*` in the package glob and the substrate's
tests in the pytest testpaths.

## Phase 2 — Downstream tiers ✅ LANDED (same caveat)

The substrate already covers all 7 tiers — Phase 1 and Phase 2 share
the same `siege/projection/` directory because the per-tier reader
pattern was uniform enough that splitting them into separate phases
of work was artificial. The bootstrap-vs-downstream distinction lives
in the slash commands (`/scaffold` is upstream-only, `/run_tier`
handles any tier).

`.claude-plugin/`:

- `skills/` — 25 skills:
  - 21 per-tier (draft / review / regen-with-feedback × 7 tiers)
  - 4 shared (mark-drafted, mark-reviewed, mark-approved,
    repair-state-drift)
- `agents/` — 7 per-tier generator subagents for fan-out
- `commands/` — `/scaffold`, `/run_tier`, `/regen_below`,
  `/continue`, `/status`

Per-tier skills reference the writer CLI inline so the steps the
skill takes are concrete (not abstract pseudocode).

## Phase 3 — Frontend retarget ✅ LANDED

Five commits across the migration branch. Confirmed landed:

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
  pointing at future MCP endpoints.
- **Cheat sheet page** at `/cheatsheet` (unauthenticated, markdown
  bundled into the build via Vite `?raw`).
- **Dev token panel** at the top of the cheat sheet — shows the
  logged-in user's JWT in copy-paste-ready `export SIEGE_TOKEN=…`
  form with expiry + relative time.

Carry-overs (`api/queue.ts` + `useQueueMutations`) kept as
Phase 4 doomed shims because editor panels still pull `Instruction`
types and `mintClientId` from them. Annotated in-source.

Verification: tsc clean, 421/421 vitest pass, 0 lint errors, vite
build succeeds.
## Deploy + on-ramp (extra, landed after Phase 3)

- **Dockerfile** picks up `siege/` + `scripts/` so the mounted
  app + bootstrap script reach the runtime container.
- **CI workflow** lints + typechecks `siege/` alongside `backend/`.
- **Plugin manifest** points at the real droplet hostname
  (`https://siege.strutco.io/siege_mcp/mcp`).
- **Bootstrap script** at `scripts/siege-bootstrap.sh` served at
  `https://siege.strutco.io/bootstrap.sh` (top-level route in
  `backend/main.py` registered before the SPA catch-all — fixed
  a 200/blank-html bug where the SPA was swallowing the request).
  Pinned by `tests/v2/test_bootstrap_routing.py`. Mirrors plugin
  contents into target project repos for mobile CC compatibility.
- **CLAUDE.md** updated: Deployment section rewritten (was stale
  Fly.io copy); new "MCP server + git-backed state" and "Cheat
  sheet (load-bearing docs)" sections.

## Phase 4 — Deletion sweep ⏸ NOT EXECUTED

See `docs/migration/deletion-inventory.md` for the punch list.

Deletion is deferred until:

1. MCP server deployed and accepting reads from the dashboard.
2. Plugin installed on mobile CC; one full chain cycle completed.
3. Dashboard fully repointed for ≥ 1 session with no fallback to
   the old backend.

The inventory doc names every file slated for deletion. ~30K LOC out,
~3.5K LOC stays in `backend/` (project CRUD, auth login, git_manager,
github OAuth, config).

## Phase 5 — Optional polish ⏸ NOT STARTED

Deferred per plan:

- Merge-conflict retry on push (multi-writer)
- Repair skills beyond `repair-state-drift`
- CI validators running `verify_dep_graph(ref)` on PRs

## Verification commands

```
# Backend smoke
cd siege-engine
.venv/bin/python -m pytest siege/tests/ -q
ruff check siege && ruff format --check siege

# Frontend (separate)
cd frontend
npx tsc -b --noEmit --force
npx vitest run
npm run lint
npx vite build
```

## Next gates (in order)

1. Deploy `siege.server:app` to the production host alongside
   the existing FastAPI app.
2. Verify `/plugin install swaggerallen/siegeengine` works on mobile
   CC; load the stub skill, list available MCP tools.
3. End-to-end one project: `/scaffold` from CC on a small test
   repo, observe state JSON + body commits, verify dashboard renders.
4. Then Phase 3 polish + Phase 4 deletion.
