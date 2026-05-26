---
name: propagate_downstream
description: Top-down regen propagation. Given a source scope (e.g. sysarch after a project-wide edit), enumerates every existing downstream scope, opens a propagation record over them, and drains the worklist by calling the appropriate per-tier regen skill on each entry. Skips fanin and the cross-tree presentational hop — both are bottom-up. Use after editing an upstream substrate / comparch / subcomparch when you want every dependent regenerated against the new content.
---

# /propagate_downstream <source>

Walks the tier chain downstream from a source scope and regenerates
every existing scope below it, in tier order. The propagation record
tracks per-entry progress so a partially-drained run resumes by gap-
fill: pending + in_progress entries get retried, done + skipped stay
put.

## Inputs

- `source` — a scope identifier, one of:
  - `sysarch` / `requirements` / `feature_expansion` — substrate-root
    sources (the project-level body changed; everything downstream is
    stale)
  - `comparch <comp_id>` — one component's design changed; that
    subtree's subcomparches + impls are stale
  - `subcomparch <parent_comp_id> <sub_id>` — one subcomponent's
    design changed; its impls are stale

  Impl sources are leaves — top-down has nothing below them. Fanin
  sources are out of scope (use a future bottom-up propagation when
  one exists).
- `ref` — git ref (default: current branch).

## What the walk includes

In tier order: `feature_expansion → requirements → sysarch →
comparch → subcomparch → impl`. The propagation enumerates **existing
state files** at each downstream tier — cold-start work (scopes
without state) is left to `/run_tier` to mint, not to this
propagation.

**Excluded by design:** `fanin` (bottom-up synthesis from impls) and
the presentational `domain_parent` cross-tree hop (also rides on
fanin). Both belong to an upward propagation when one exists.

## Steps

1. **Parse source.** Build a JSON scope object from the user-provided
   args.
2. **Preview the worklist** (optional, for big projects):
   `python3 -m siege.cli compute-downstream --source-scope-json '...'`
   shows what would be enqueued without writing anything. Skip if the
   source is narrow (comparch / subcomparch).
3. **Open the propagation** in one call:

   ```
   python3 -m siege.cli open-propagation \
     --op-type propagate_downstream \
     --from-source-scope-json '{"tier": "<source-tier>", ...}'
   ```

   Stash the returned `propagation_id`. The walk runs server-side; the
   record materializes on disk at `state/propagations/<id>.json`. Git
   add + commit that file before draining (so resume-after-restart
   can see it).

4. **Per entry, in tier order** (the worklist already comes back
   sorted by `TOP_DOWN_CHAIN` order):
   a. `python3 -m siege.cli update-propagation-entry --propagation-id $pid --scope-json '...' --status in_progress`
   b. Dispatch to the per-tier regen skill based on `scope.tier`:
      - `feature_expansion` → `regen-feature-expansion-with-feedback`
      - `requirements` → `regen-requirements-with-feedback`
      - `sysarch` → `regen-sysarch-with-feedback`
      - `comparch` → `regen-comparch-with-feedback` (pass `comp_id`)
      - `subcomparch` → `regen-subcomparch-with-feedback` (pass `parent_id`, `sub_id`)
      - `impl` → `regen-impl-with-feedback` (pass `parent_id`, `sub_id`, `phase`)

      Each regen skill carries the prior review forward as feedback,
      drafts a new body, fires the next-tier review, commits.
   c. `python3 -m siege.cli update-propagation-entry --propagation-id $pid --scope-json '...' --status done`
   d. If a regen fails three times consecutively, surface the error
      and stop the propagation drain (status stays `open`; user can
      resume after investigating).
5. **Final report.** When the worklist is fully drained the
   propagation rolls up to `complete` automatically — no separate
   close call. Print the propagation_id, tier-by-tier counts, and
   the total count of regenerated scopes.

## Don't

- Don't drain `approved` scopes without intent — the regen skills
  block on the approval gate by default. Propagation from an
  upstream change implies "force regen" (the upstream content is
  what changed; downstream's approval is now stale). Pass
  `force=True` through to the regen skill in this flow.
- Don't continue past 3 consecutive validation failures — surface
  and stop.
- Don't open a second propagation while one is open for the same
  source subtree. Resume the existing one instead — the `add_entries`
  helper extends a worklist non-destructively if mid-drain upstream
  shifts add new candidates.

## Output

```
source: <source-scope>
propagation_id: prop_<id>
worklist: N scopes (X comparch, Y subcomparch, Z impl, …)
drained: N done, M skipped (final)
remaining: 0 pending
status: complete
```

## Notes

The walk is purely topological — it doesn't filter by review score
or staleness markers. If you want "only the lowest-scoring scopes",
use `/regen_below` instead; if you want "only the scopes whose
upstream sha actually changed", that gate doesn't exist yet (state
JSON doesn't record upstream shas — see v3-spec §Propagation).
