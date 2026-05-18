# SiegeEngine cheat sheet

The compact reference for the SiegeEngine plugin + dashboard. Read
this first when you sit down to work; bookmark `siege.strutco.io/
cheatsheet` for the live in-app copy.

This file is **load-bearing documentation** — it's what users see
when they hit the dashboard's cheat sheet page. When you add a slash
command, ship a new skill, or change a workflow, update this file in
the same commit. The endpoint at `/siege_mcp/api/cheatsheet` serves
it raw; the frontend at `/cheatsheet` renders it as markdown.

## TL;DR

1. **Setup once**: on desktop CC, `/plugin install swaggerallen/siegeengine`.
   On mobile CC (no `/plugin` support), run
   `curl -fsSL https://siege.strutco.io/bootstrap.sh | bash` inside
   the project repo and commit the changes.
2. **Bootstrap a fresh project**: `/scaffold` from inside a CC
   session opened on the project repo. Walks features → requirements
   → sysarch end-to-end.
3. **Drive a tier**: `/run_tier comparch` (or any other tier). Drafts
   + reviews every absent scope at that tier in topological order.
4. **Iterate on quality**: `/regen_below comparch 70` regenerates
   every scope at the tier whose review score is below the threshold,
   carrying the prior review forward as feedback.
5. **Catch up**: `/status` for a per-tier snapshot; `/continue
   <batch_id>` to resume an interrupted batch.

## Workflow patterns

### Fresh project end-to-end

```text
1. Open the project's repo in Claude Code on your laptop or mobile.
2. /scaffold
   → drafts + reviews features, requirements, sysarch in order.
   → pauses for user inspection between tiers unless auto_approve.
3. Review each tier's drafts (open the dashboard at siege.strutco.io
   → branch selector → eyeball worst-scored scopes).
4. /run_tier comparch
   → fan-out across foundation comps first, then non-foundation.
5. Repeat /run_tier subcomparch, /run_tier impl.
6. /run_tier fanin once the bottom is settled.
```

### Iteration cycle on one tier

```text
1. /status (or open the dashboard's tier-ops page) to find the
   bottom of the score distribution.
2. /regen_below <tier> <threshold> — typically threshold is 70.
3. Wait for the batch to complete (check /status or watch the
   dashboard).
4. Inspect the new scores. If still too low: edit the prompt at
   siege_mcp/prompts/<tier>.md, commit, re-run /regen_below.
5. Once scores plateau, /run_tier <tier> with auto_approve=true
   to cover the full-corpus tail.
```

### Manual one-scope drafting

```text
1. /draft <tier> <id>           (or "draft <tier> <id>" in chat)
2. /review <tier> <id>          (auto-fires after draft in most flows)
3. /mark-approved <tier> <id>   when satisfied
```

### Resume after a crash / disconnect

```text
1. /status — note the batch id in flight (look for status=partial).
2. /continue <batch_id> — re-fires only the scopes that didn't
   complete; finished work stays put.
```

## Slash commands

All commands live at `.claude-plugin/commands/` in the repo and are
shipped with the plugin install.

| Command | What it does |
|---|---|
| `/scaffold` | Bootstrap upstream chain (features → requirements → sysarch). Sequential per-tier. Pauses for review between tiers unless `auto_approve=true`. |
| `/run_tier <tier>` | Draft + review every absent/drafted scope at one tier, in topological order. Foundation comps first for comparch; layer-by-layer for sub-tiers. |
| `/regen_below <tier> <threshold>` | Regenerate every scope at the tier whose review score is below the threshold. Threads prior review forward as feedback. Mints a batch state file. |
| `/continue <batch_id>` | Resume an interrupted batch — fills gaps, doesn't redo completed work. |
| `/status` | Per-tier snapshot: counts of absent/drafted/reviewed/approved, score histogram, worst-N scopes. Read-only, no commits. |

## Skills (called automatically by commands, or directly)

Each skill is a single self-contained workflow. Commands compose
them; you can also invoke a skill directly if you only want one step.

### Per-tier (×7 tiers: feature_expansion, requirements, sysarch, comparch, subcomparch, impl, fanin)

- `draft-<tier>` — Fetch context, compose body, validate, commit +
  push state JSON + body in one commit.
- `review-<tier>` — Fetch review context, produce `<review>` XML,
  commit + push state JSON + review.md.
- `regen-<tier>-with-feedback` — Same as draft, but threads the
  prior review forward as `prior_review_text`. Fires a fresh review
  after.

### Shared

- `mark-drafted` — Repair: re-sync state JSON to a hand-edited body.
- `mark-reviewed` — Repair: re-sync state JSON to a hand-edited
  review.md.
- `mark-approved` — Final gate: flip `reviewed` → `approved`.
  Downstream tiers see approved content as canonical.
- `repair-state-drift` — Recompute `body_sha256` when the MCP server
  reports a drift between state JSON and the actual body bytes.

## Dashboard pages (siege.strutco.io)

| Page | What it shows |
|---|---|
| `/` | Project list. Pick a project to enter the workspace. |
| `/projects/:id/workspace` | Per-tier read views. Branch selector in the header switches the git ref every read is taken against. |
| `/projects/:id/tiers/:tier/structure` | Per-tier structure summary — comps, deps, foundation markers, kinds. |
| `/projects/:id/tiers/:tier/reviews` | Score histogram + worst-N intros, scoped by batch_id if provided. |
| `/cheatsheet` | This page. |

## Score bands

Reviews emit an integer 0-100. The bands:

- **0-30**: fundamental rework needed
- **31-60**: structural fixes
- **61-85**: minor refinements
- **86-100**: ready to approve

Per-tier score baselines shift after prompt or context changes —
don't compare scores from before/after a `siege_mcp/prompts/<tier>.md`
edit as if they were on the same scale.

## State + git conventions

Every state transition is one git commit. The state file lives at
`state/<tier>/<id>.json` (top-level) or
`state/<tier>/<parent_id>/<sub_id>.json` (sub-tier). The body lives
at `<tier>/<id>/body.md` next to its `review.md`. State JSON carries
`body_sha256` for drift detection.

Full schema: `docs/migration/state-schema.md`.

## Install (one-time)

### Desktop Claude Code (laptop / CLI)

```text
/plugin install swaggerallen/siegeengine
```

Installs persist across CC sessions on the same device.

### Mobile Claude Code (no `/plugin` support yet)

From inside the project repo you want to drive (in a CC session
that has shell access, or by asking Claude to run it for you):

```bash
curl -fsSL https://siege.strutco.io/bootstrap.sh | bash
```

The bootstrap:

- Writes `.mcp.json` pointing at `https://siege.strutco.io/siege_mcp/mcp`
- Mirrors `.claude/commands/`, `.claude/skills/`, and `.claude/agents/`
  from the SiegeEngine repo (5 slash commands, 25 skills, 7 per-tier
  generator subagents)
- Adds a "Working with SiegeEngine" section to `CLAUDE.md`

Then commit + push the new files. Mobile CC will pick them up the
next time it opens the repo — no plugin install required.

**Auth**: export `SIEGE_TOKEN` (your JWT from `siege.strutco.io`) in
the shell environment so `.mcp.json`'s `Authorization: Bearer
${SIEGE_TOKEN}` header is populated. Add it to `~/.bashrc` /
`~/.zshrc` to persist.

Re-run the bootstrap any time to pull the latest commands + skills
into the project repo. The script is idempotent and only touches the
SiegeEngine-managed files.

## Common gotchas

- **Don't push to a branch you don't own.** Skills target whatever
  branch is currently checked out by default; pass `ref=<branch>`
  explicitly if you want to push elsewhere.
- **Don't run `/scaffold` on a populated project.** It'll happily
  re-draft tier scopes that already exist. Use `/run_tier` if some
  tiers are populated and you only want to fill in the gaps.
- **Reviews are advisory.** A scope can be approved with a low
  score; the score is a quality signal, not a gate. Approval is a
  user decision.
- **Approved scopes don't auto-regen.** `/regen_below` skips
  approved scopes. If you want to regen an approved scope, run
  `regen-<tier>-with-feedback <id>` directly — that path is
  explicit-only by design.
- **Drift on an approved artifact = something serious.** The
  `repair-state-drift` skill refuses to silently fix drift on
  approved scopes without explicit confirmation. Investigate
  before papering over.
