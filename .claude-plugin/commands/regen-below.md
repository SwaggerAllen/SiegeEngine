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
2. **Open a propagation.** Run `python3 -m siege.cli open-propagation --op-type regen_below_threshold --tier $tier --threshold $threshold --worklist-json '[{...}, ...]'` where each entry is `{"scope": {tier, comp_id?, parent_id?, sub_id?, phase?}, "status": "pending"}`. For `impl` / `fanin` candidates, the scope entry MUST include its `phase` field (the review summary payload carries it) — `/continue` re-fires off these scope keys and a phase-less impl/fanin key never resolves. Stash the returned `propagation_id`.
3. **Mint a batch.** Write a `state/batches/batch_<id>.json` recording
   op_type=`regen_below_threshold`, tier=$tier, threshold=$threshold,
   the scope list, status=`pending`. Pass `meta={"batch_id": "<id>"}`
   on the open-propagation call so the two records pair up. The batch
   stays the queue-level record; the propagation is the per-entry
   progress ledger ``/status`` shows.
4. **Per scope, in order:**
   a. Call `python3 -m siege.cli update-propagation-entry --propagation-id $pid --scope-json '{...}' --status in_progress`.
   b. Call `regen-<tier>-with-feedback`. It carries the review forward,
      drafts a new body, fires a review, commits. For `impl` / `fanin`,
      pass the candidate's `phase` through to the regen skill.
   c. Call `python3 -m siege.cli update-propagation-entry --propagation-id $pid --scope-json '{...}' --status done` once the regen commits. (Skip with `--status skipped` if the candidate disappears, e.g. mid-drain reset.)
   d. Update the batch's status as you go (in-place commits to the
      batch JSON, one per scope completed).
5. **Final batch commit:** status=`complete | partial | failed` plus
   the new score histogram for comparison. The propagation rolls up
   to `complete` automatically once every entry is `done` or
   `skipped` — no separate "close" call.
6. **Report deltas.**

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
propagation_id: prop_<id>
```
