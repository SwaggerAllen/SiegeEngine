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

## Phased projects: impl + fanin defer to /run_phase

The impl and fanin tiers are **phased** — a leaf subcomponent gets one
impl node per phase it picks up work in, and fan-in recomputes per
phase. If a phase registry exists (`compute_plan` returns a non-empty
`phases` list), do **not** blind-fan `/run_tier impl` or
`/run_tier fanin` across every node at once — that ignores phase
ordering and the cross-phase delta context.

Instead, for `tier` in (`impl`, `fanin`) when the project is phased:

1. Call `mcp__siegeengine__compute_plan(ref=$ref)`. If it reports
   `errors`, stop and surface them — the plan isn't safe to run.
2. Run each phase in ascending `order`, exactly as `/run_phase <n>`
   does (draft + review the phase's `build_order`, then its fan-in).
   Equivalent to `/run_phase 1; /run_phase 2; …` for every phase in
   the registry. Defer to `commands/run-phase.md` for the per-phase
   procedure.

For an **unphased** project (no registry — `compute_plan` returns an
empty `phases` list, or every impl/fanin scope has `phase: null`),
fall through to the generic per-tier flow below.

## Steps

1. **Enumerate the scope set.**
   - **comparch / subcomparch** — run `python3 -m siege.cli list-scopes
     --tier $tier` from the repo root. It reads the upstream identity
     ledgers (`ids/sysarch/` for comparch, `ids/comparch/` for
     subcomparch) and prints every scope the tier should have —
     *including ones not yet drafted* — each with its `status`,
     `alias`, and `is_foundation`. This is what closes the fanout
     gap: a freshly-approved sysarch already names every comparch
     scope. Process them in the order returned — foundation first,
     then declaration order. Finer dependency-aware ordering (holding
     a comp until its non-foundation deps approve) is a projection
     refinement still to come; until then a `/run_tier` re-run fills
     any gap left by a scope drafted before its deps settled.
   - **impl / fanin** on an unphased project — call
     `mcp__siegeengine__get_structure_summary(ref=$ref, tier=$tier)`
     and enumerate from it leaf-first (fanin bottom-up).
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
