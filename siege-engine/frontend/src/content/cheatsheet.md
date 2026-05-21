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
4. **Phase a large project**: once subcomparch is done, write a phase
   registry, `/mint_plan` to compute the plan, then `/run_phase 1`,
   `/run_phase 2`, … to build the impl + fan-in slice phase by phase.
5. **Iterate on quality**: `/regen_below comparch 70` regenerates
   every scope at the tier whose review score is below the threshold,
   carrying the prior review forward as feedback.
6. **Catch up**: `/status` for a per-tier snapshot; `/continue
   <batch_id>` to resume an interrupted batch.

## Workflow patterns

### Fresh project end-to-end

```text
1. Open the project's repo in Claude Code on your laptop or mobile.

2. Get the input doc in front of /scaffold. Four equivalent paths
   (in precedence order):
   a. /scaffold input_doc=docs/my-spec.md
   b. /scaffold @docs/my-spec.md          ← CC's @-file attach
   c. paste the spec text into chat, then /scaffold
   d. drop the spec at seed-docs/<name>.md and run /scaffold with
      no args — auto-discovered from seed-docs/

3. /scaffold drafts + reviews features, requirements, sysarch in
   order. Pauses between tiers for user inspection unless
   auto_approve=true.

4. Review each tier's drafts (open the dashboard at
   siege.strutco.io → branch selector → eyeball worst-scored scopes).

5. /run_tier comparch  → fan-out across foundation comps first,
                         then non-foundation.

6. Repeat /run_tier subcomparch.
7. /run_tier impl     → unphased: drafts every impl node at once.
                        For a large project, phase it instead (below).
8. /run_tier fanin once the bottom is settled.
```

The input doc shapes everything downstream. One or two pages of
focused prose (problem statement, target users, system qualities,
primary workflows) beats ten pages of category-speak — extraction
tiers compress hard, so vague input produces vague handles all the
way down.

### Phased build (large projects)

The five architecture tiers (features → subcomparch) always build
**whole** — the entire design exists before any code-territory work.
Phasing partitions only the **impl tier**: a leaf subcomponent gets
one impl node per phase in which it picks up new feature work, and
fan-in recomputes per phase. Each phase's impl node implements the
cumulative responsibility closure and is authored delta-style against
the prior phase.

```text
1. Write a phase registry: one state/phases/<phase_id>.json per phase,
   each {schema_version, phase_id, name, order (int), description,
   feature_ids: [...]}. order is linear (1, 2, 3, …); feature_ids
   assigns features to that phase. This is your release-planning
   intent — the planner reads it and never mutates it.

2. /mint_plan — runs compute_plan, writes state/plan.json, and
   pre-creates one absent-status impl state file per planned node
   with its responsibility closure seeded. Idempotent: re-run it any
   time the registry / comparch / subcomparch changes.

3. /run_phase 1 — builds phase 1's impl nodes (topologically) then
   its fan-in. Then /run_phase 2, /run_phase 3, … in order.
   /run_tier impl on a phased project does this for you, all phases.
```

A dependency can pull a component earlier than its assigned phase
(if comp A is assigned phase 3 but comp B in phase 2 depends on it, A
is scheduled in phase 2). `compute_plan` does this automatically and
records every such **rearrangement** in `state/plan.json` — the
registry stays untouched, but you see what moved and why. An
unassigned feature is a hard error that blocks `/run_phase`.

### Iteration cycle on one tier

```text
1. /status (or open the dashboard's tier-ops page) to find the
   bottom of the score distribution.
2. /regen_below <tier> <threshold> — typically threshold is 70.
3. Wait for the batch to complete (check /status or watch the
   dashboard).
4. Inspect the new scores. If still too low: edit the prompt at
   siege/prompts/<tier>.md, commit, re-run /regen_below.
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
| `/run_tier <tier>` | Draft + review every absent/drafted scope at one tier, in topological order. Foundation comps first for comparch; layer-by-layer for sub-tiers. On a phased project, `/run_tier impl` and `/run_tier fanin` defer to `/run_phase` per phase. |
| `/mint_plan` | Materialize the impl-tier phasing plan: runs `compute_plan`, writes `state/plan.json`, pre-creates one absent impl node per planned `(subcomponent, phase)`. Idempotent + additive. |
| `/run_phase <n>` | Build phase `order=n`'s slice — draft + review every impl node in topological build order, then the phase's fan-in. Recomputes the plan live and refuses on divergence or hard errors. |
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

The `impl` and `fanin` draft / review / regen skills take an optional
`phase` — set it for a phased node and the skill computes the `p<N>`
path layout and stamps schema v2; omit it for an unphased project.

### Shared

- `mint-plan` — Compute + materialize the phasing plan: `state/plan.json`
  plus one absent impl node per planned `(subcomponent, phase)`.
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
don't compare scores from before/after a `siege/prompts/<tier>.md`
edit as if they were on the same scale.

## State + git conventions

Every state transition is one git commit. The state file lives at
`state/<tier>/<id>.json` (top-level) or
`state/<tier>/<parent_id>/<sub_id>.json` (sub-tier). The body lives
at `<tier>/<id>/body.md` next to its `review.md`. State JSON carries
`body_sha256` for drift detection.

**Phased impl / fanin (schema v2).** A phased node carries
`scope.phase` and lands at a `p<N>` path: impl at
`state/impl/<parent>/pN/<sub>.json` · `impl/<parent>/subs/<sub>/pN/body.md`;
fanin at `state/fanin/<comp>/pN.json` · `fanin/<comp>/pN/body.md`.
Unphased (schema v1) nodes keep the legacy paths above. The phase
registry lives at `state/phases/<phase_id>.json`; the computed plan
at `state/plan.json`.

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
  from the SiegeEngine repo (6 slash commands, 26 skills, 7 per-tier
  generator subagents)
- Adds a "Working with SiegeEngine" section to `CLAUDE.md`

Then commit + push the new files. Mobile CC will pick them up the
next time it opens the repo — no plugin install required.

**Auth**: this page (when you're logged in) shows your JWT at the
top in a copy-paste-ready `export SIEGE_TOKEN=…` form. Paste it into
your shell; add it to `~/.bashrc` / `~/.zshrc` to persist across
sessions. The `.mcp.json` the bootstrap writes references
`${SIEGE_TOKEN}` so CC's MCP client substitutes it at request time.
Tokens last 30 days — come back here when one expires.

Re-run the bootstrap any time to pull the latest commands + skills
into the project repo. The script is idempotent and only touches the
SiegeEngine-managed files.

## Troubleshooting

When MCP calls from CC fail with a clone error like "Clone of
`<repo>` requires authentication", the three things to check are
already on this page when you're logged in — see the **Auth
diagnostic** panel near the top:

- **JWT sub** — the user id the MCP server sees on every request.
- **Dashboard user (`/auth/me`)** — confirms the same JWT resolves
  to a real user server-side. A mismatch with `sub` means you have
  two accounts; log out, log back in as the right user, copy the
  new `SIEGE_TOKEN` from the **Your dev token** panel.
- **GitHub connected** — confirms a `GitHubCredential` row exists
  for this user. Without one, private-repo clones from the MCP
  server fail. Connect via **Project Settings → GitHub
  connection** on any project.

The "refresh" button on the diagnostic panel re-runs the checks
without reloading the page, so you can verify a fresh re-authorize
landed.

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
