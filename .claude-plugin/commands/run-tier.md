---
name: run_tier
description: Run draft + review for every pending scope at a tier. Topologically respects within-tier dependencies (foundation comps first for comparch, layer-by-layer for subcomparch + impl). Use after /scaffold to drive the downstream chain forward, one tier at a time.
---

# /run_tier <tier>

Process every scope at the given tier that isn't yet `reviewed` or
`approved`. Topologically ordered within the tier.

## Inputs

- `tier` — one of comparch / subcomparch / impl / fanin (or any of
  the bootstrap tiers if you want to re-run them)
- `ref` — git ref
- (optional) `auto_approve` — if true, approve each reviewed scope.
  Default: false.

## Steps

1. **Read structure.** Call `mcp__siegeengine__get_structure_summary(ref=$ref, tier=$tier)`.
   Use it to enumerate the scope set + figure out topological order:
   - **comparch**: foundation comps first (those with `is_foundation: true`),
     then non-foundation comps that depend only on already-approved deps.
   - **subcomparch / impl**: layer by layer, leaf-first.
   - **fanin**: bottom-up; presentational comps gate on their domain_parent
     fanins being populated (see `queries.all_domain_parents_have_populated_fanin`
     in the old backend for the exact gate logic).
2. **Per scope, in order:**
   a. Call `draft-<tier>` (skipping if status is already `drafted`/`reviewed`/`approved`).
   b. Call `review-<tier>` (skipping if already reviewed).
   c. If `auto_approve`, call `mark-approved`.
3. **Stop on first persistent failure.** If a scope fails validate 3
   times in a row, surface the error and stop. The user can fix the
   prompt or context and re-run.
4. **Report.** Histogram of scores + counts of drafted / reviewed /
   approved / failed.

## Fan-out (optional)

When the tier has > 1 ready scope at the same topological layer, the
orchestrator MAY fan out to per-tier generator subagents
(`agents/generator-<tier>`) for parallel drafting. Reviews serialize
behind drafts so context stays consistent.

## Output

```
tier=$tier
ready: N scopes
drafted: N (+ M existing)
reviewed: N
approved: N
failed: N — <one-line per failure>
score histogram: 0-30:N | 31-60:N | 61-85:N | 86-100:N
```
