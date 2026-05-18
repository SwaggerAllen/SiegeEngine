---
name: regen-subcomparch-with-feedback
description: Regenerate a subcomparch draft using the prior review as feedback. Reads `get_state` to pull the prior review text, runs the same flow as `draft-subcomparch` but threads the review in as `prior_review_text` so the LLM addresses the findings. Triggers when the user says "regen subcomparch <id> from review", "/regen_subcomparch <id>", or as part of `/regen_below`.
thinking_effort: default
---

# Regen a subcomparch with prior-review feedback

This is `draft-subcomparch` with the prior review text threaded in. The
prior review rides forward as `prior_review_text` in the new draft's
state JSON so it stays visible in the commit history and so future
re-reviews can compare deltas.

## Inputs

- `ref` — git ref
- `parent_id` — owning comparch id ; `sub_id` — sub id under the parent

## Steps

1. **Read state.** Call `mcp__siegeengine__get_state`. The scope must
   be in `reviewed` status with a populated `review` block (the review
   text lives at `review.body_path`). If `reviewed` but no review text,
   stop and surface the inconsistency for the user to repair.
2. **Pull prior review text.** Read the file at `review.body_path` from
   the ref. This is the `<review>...</review>` XML that the previous
   review pass produced.
3. **Call draft-subcomparch** logic with `prior_review_text` set to the
   text from step 2. The generator MUST address the review's findings
   — sloppy regen is worse than no regen because the score won't move.
4. **The new draft replaces the old one.** Update the state JSON to
   reflect `status="drafted"` again, with the new body's sha256. The
   prior review block is **dropped** (cleared) — a fresh review pass
   has to fire against the new draft.
5. **Auto-fire the review** as a follow-up (call `review-subcomparch` in
   the same session if running interactively; skip if running under
   a batch orchestrator that fires reviews separately).
6. **Commit + push.** Single commit:
   `regen(subcomparch/$id): <one-line summary> [from review score=<N>]`

## Don't

- Don't lose the prior review by clearing the review block before
  carrying its text into the new draft's `prior_review_text`.
- Don't regen an `approved` scope without explicit confirmation.

## Output

One line: what changed in the new draft + the commit sha.
