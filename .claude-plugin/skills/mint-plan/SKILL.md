---
name: mint-plan
description: Materialize the impl-tier phasing plan. Calls `compute-plan`, writes `state/plan.json`, and mints one `absent`-status impl state JSON per planned node (phase-scoped, with the responsibility closure pre-seeded). Idempotent and additive — never touches a node already drafted+. Triggers on "mint plan", "/mint_plan", or before the first `/run_phase`.
---

# Mint the phasing plan

`compute-plan` is a pure projection — it *describes* the per-phase
impl nodes but writes nothing. This skill is the writer: it runs
`compute-plan`, persists the plan, and pre-creates the impl state
files so `/run_phase` has something concrete to draft into.

Run this once after the phase registry (`state/phases/<id>.json`) is
written, and again any time the registry, comparch, or subcomparch
tiers change.

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)

## Steps

1. **Compute the plan.** Run `python3 -m siege.cli compute-plan`.
2. **Refuse on hard errors.** If the result's `errors` list is
   non-empty, STOP. Surface every error verbatim and do not write
   anything. Hard errors (an unassigned feature, a closure that
   changed under an already-drafted node) mean the plan is not safe
   to materialize — the user fixes the registry or regenerates the
   stale node, then re-runs `mint-plan`.
3. **Write `state/plan.json`.** Serialize the `compute-plan` result
   verbatim (it already has `schema_version`, `ref`, `computed_at`,
   `phases`, `rearrangements`, `errors`, `warnings`, `aggregates`).
4. **Surface rearrangements.** If `rearrangements` is non-empty, print
   each `line` — these are components a dependency pulled earlier than
   their assigned phase. The registry was NOT mutated; this is the
   report the user asked for. Not an error, just visibility.
5. **Mint the impl nodes.** From the repo root, call the writer CLI's
   `mint-plan` subcommand. It reads `state/plan.json` and, for each
   planned impl node, writes an `absent`-status impl state JSON at the
   phased path with `meta.parent_resps` pre-seeded to the node's
   cumulative `closure_resp_ids`. It is **idempotent and additive**:
   a node already at `drafted` / `reviewed` / `approved` is left
   untouched; an `absent` node is re-seeded (the closure may have
   grown). It also reports — but never deletes — phased impl nodes on
   disk that the new plan no longer includes.

   ```bash
   python3 -m siege.cli mint-plan
   ```

   It prints a JSON object with `minted`, `reseeded`, `skipped_built`,
   and `dropped_by_plan` — each a list of impl state paths.

6. **Stage + commit + push.** One commit with `state/plan.json` and
   every minted/re-seeded impl state JSON:
   `mint-plan: <N> impl nodes across <M> phases`
   Push with `git push -u origin $ref` (retry on network failure up
   to 4 times with 2s / 4s / 8s / 16s backoff).

## Don't

- Don't materialize anything when `compute-plan` reports `errors`.
- Don't overwrite a `drafted` / `reviewed` / `approved` impl node —
  re-planning is additive, never destructive.
- Don't delete the `dropped_by_plan` nodes. Surface them so the user
  decides — a dropped node usually means a registry edit removed a
  feature; the user may want to keep the built artifact or clean it
  up deliberately.
- Don't touch the phase registry (`state/phases/`). It is the user's
  intent; the planner only reads it.
- Don't create a PR.

## Output

A summary:

```
plan: <M> phases, <N> impl nodes
minted: N new absent nodes
reseeded: N existing absent nodes (closure refreshed)
skipped: N already-built nodes (left untouched)
rearrangements: N — <one line each>
dropped-by-plan: N — <path each, surfaced for review>
commit: <sha>
```
