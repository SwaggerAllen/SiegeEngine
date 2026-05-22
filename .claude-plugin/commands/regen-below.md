---
name: regen_below
description: Regenerate every scope in a tier whose review score is below a threshold. Wraps regen-<tier>-with-feedback per scope. Each regen reads the prior review and threads it forward, so scoped quality issues get addressed one round at a time.
---

# /regen_below <tier> <threshold>

Targeted regen of the bottom-of-distribution. The threshold is an
integer 0-100; every scope at the tier with a review score strictly
less than the threshold gets regenerated.

## Inputs

- `tier` — same set as `/run_tier`
- `threshold` — int 0-100
- `ref` — git ref

## Steps

1. **Read review summary.** Run `python3 -m siege.cli get-review-summary --tier $tier`.
   Use the per-scope scores to identify candidates: scope.score is
   not None AND scope.score < threshold AND status is `reviewed`.
2. **Mint a batch.** Write a `state/batches/batch_<id>.json` recording
   op_type=`regen_below_threshold`, tier=$tier, threshold=$threshold,
   the scope list, status=`pending`. For `impl` / `fanin` candidates,
   each scope entry MUST include its `phase` field (the review summary
   payload carries it) — `/continue` re-fires off these scope keys and
   a phase-less impl/fanin key never resolves.
3. **Per scope, in order:**
   a. Call `regen-<tier>-with-feedback`. It carries the review forward,
      drafts a new body, fires a review, commits. For `impl` / `fanin`,
      pass the candidate's `phase` through to the regen skill.
   b. Update the batch's status as you go (in-place commits to the
      batch JSON, one per scope completed — keeps progress visible
      if the orchestrator dies mid-batch).
4. **Final batch commit:** status=`complete | partial | failed` plus
   the new score histogram for comparison.
5. **Report deltas.**

## Don't

- Don't regen `approved` scopes (they're filtered out by the
  `status=reviewed` check above).
- Don't continue past 3 consecutive validation failures — surface
  and stop.

## Output

```
tier=$tier threshold=$threshold
candidates: N (scores below threshold)
regenerated: N
deltas: mean N→N (median N→N)
new histogram: 0-30:N | 31-60:N | 61-85:N | 86-100:N
batch_id: <id>
```
