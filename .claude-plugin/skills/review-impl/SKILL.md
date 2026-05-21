---
name: review-impl
description: Review a impl draft. Reads `get_review_context` for the scope, produces a `<review>` XML block per the parser contract, writes it as review.md, updates state JSON, commits, and pushes. Triggers automatically after a `draft-impl` or on manual `/review_impl <id>`.
thinking_effort: default
---

# Review a impl

You are reviewing one drafted impl. The output is a single
`<review>` XML block (see `siege/parsers/review_xml.py` for the
exact schema). Score is 0-100; bands are 0-30 (rework), 31-60
(structural fixes), 61-85 (refinements), 86-100 (ready).

## Inputs

- `ref` — git ref
- `parent_id` — owning comparch id ; `sub_id` — sub id under the parent
- (optional) `phase` — phase index for a phased impl node; omit for an
  unphased (legacy) impl. Must match the `phase` the node was drafted
  at, or `get_state` / the paths below address the wrong node.

## Steps

1. **Read the draft state.** Call
   `mcp__siegeengine__get_state(ref=$ref, tier="impl", parent_id=$parent_id, sub_id=$sub_id, phase=$phase)`
   (omit `phase` for an unphased impl) to confirm the scope is in
   `drafted` status with a valid draft block. If it's already
   `reviewed` or `approved`, ask the user whether to re-review (most
   of the time this is a mistake).
2. **Fetch review context.** Call
   `mcp__siegeengine__get_review_context(ref=$ref, tier="impl", parent_id=$parent_id, sub_id=$sub_id, phase=$phase, draft_sha=<draft.body_sha256 from state>)`.
3. **Compose the review.** Produce one `<review>...</review>` block
   following the schema:
   - `<intro>` — 3-6 sentence "how close to finished" read (display only)
   - `<score>` — integer 0-100
   - `<handles-structure>` — per-finding `<finding id="hN">` entries
   - `<architectural-decisions>` — same shape; rename to
     "decomposition axis critique" on tiers without explicit tech
     decisions (expansion / requirements / fanin)
4. **Validate inline.** Run `parse_review` mentally — if any section
   is missing or empty, fix and re-emit.
5. **Write the review.** Phased node (`phase` set) →
   `impl/$parent_id/subs/$sub_id/p$phase/review.md`; unphased →
   `impl/$parent_id/subs/$sub_id/review.md`.
6. **Materialize state JSON.** From the repo root, call the writer
   CLI. The bash computes the phased vs unphased review path from
   `$phase` and passes `--phase` only when the node is phased; the
   CLI extracts `<score>` and `<intro>`, computes the review sha256,
   writes the `review` block, flips status to `reviewed`, and mints a
   fresh nonce:

   ```bash
   PHASE="${phase:-}"
   if [ -n "$PHASE" ]; then
     REVIEW_PATH="impl/$parent_id/subs/$sub_id/p$PHASE/review.md"
     PHASE_ARG=(--phase "$PHASE")
   else
     REVIEW_PATH="impl/$parent_id/subs/$sub_id/review.md"
     PHASE_ARG=()
   fi
   python3 -m siege.cli write-review \
     --tier impl \
     --parent-id "$parent_id" \
     --sub-id "$sub_id" \
     "${PHASE_ARG[@]}" \
     --review-path "$REVIEW_PATH"
   ```

   It prints a JSON line with `state_path`, `score`, and
   `intro_first_sentence`. A non-zero exit means the review was
   rejected — `<score>` missing or out of the 0-100 range, `<intro>`
   missing or empty, or the scope not in `drafted` status. Fix the
   review (or re-fetch the scope) and re-run.
7. **Stage both files**, commit:
   `review(impl/$id): score=<N> — <intro first sentence>`
8. **Push.**

## Don't

- Don't review a scope that isn't `drafted` (without confirmation).
- Don't omit the `<intro>` or emit a non-integer `<score>`.
- Don't reuse a stale `draft_sha` — re-fetch state if you've been
  idle and someone might have re-drafted.

## Output

One line: `score=<N> — <intro first sentence>`, plus the commit sha.
