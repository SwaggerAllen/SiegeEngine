---
name: regen-impl-with-feedback
description: Regenerate a impl draft using the prior review as feedback. Reads `get_state` to pull the prior review text, runs the same flow as `draft-impl` but threads the review in as `prior_review_text` so the LLM addresses the findings. Triggers when the user says "regen impl <id> from review", "/regen_impl <id>", or as part of `/regen_below`.
thinking_effort: default
---

# Regen a impl with prior-review feedback

This is `draft-impl` with the prior review text threaded in. The
prior review rides forward as `prior_review_text` in the new draft's
state JSON so it stays visible in the commit history and so future
re-reviews can compare deltas.

## Inputs

- `ref` — git ref
- `parent_id` — owning comparch id ; `sub_id` — sub id under the parent
- (optional) `phase` — phase index for a phased impl node; omit for an
  unphased (legacy) impl. Thread the same value through every step —
  `get_state`, the draft-impl call, and the paths.

## Steps

1. **Read state.** Call
   `mcp__siegeengine__get_state(ref=$ref, tier="impl", parent_id=$parent_id, sub_id=$sub_id, phase=$phase)`
   (omit `phase` for an unphased impl). The scope must be in
   `reviewed` status with a populated `review` block (the review text
   lives at `review.body_path`). If `reviewed` but no review text,
   stop and surface the inconsistency for the user to repair.
2. **Pull prior review text.** Read the file at `review.body_path` from
   the ref. This is the `<review>...</review>` XML that the previous
   review pass produced.
3. **Call draft-impl** logic with `prior_review_text` set to the
   text from step 2, and `phase` passed through unchanged. The
   generator MUST address the review's findings — sloppy regen is
   worse than no regen because the score won't move.
4. **The new draft replaces the old one.** Update the state JSON to
   reflect `status="drafted"` again, with the new body's sha256. The
   prior review block is **dropped** (cleared) — a fresh review pass
   has to fire against the new draft.
5. **Auto-fire the review** as a follow-up (call `review-impl` in
   the same session if running interactively; skip if running under
   a batch orchestrator that fires reviews separately).
6. **Commit + push.** Single commit:
   `regen(impl/$id): <one-line summary> [from review score=<N>]`

## Don't

- Don't lose the prior review by clearing the review block before
  carrying its text into the new draft's `prior_review_text`.
- Don't regen an `approved` scope without explicit confirmation.

## Output

One line: what changed in the new draft + the commit sha.
