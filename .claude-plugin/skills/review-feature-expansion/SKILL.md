---
name: review-feature-expansion
description: Review a feature expansion draft. Reads `get_review_context` for the scope, produces a `<review>` XML block per the parser contract, writes it as review.md, updates state JSON, commits, and pushes. Triggers automatically after a `draft-feature_expansion` or on manual `/review_feature_expansion <id>`.
thinking_effort: max
---

# Review a feature expansion

You are reviewing one drafted feature expansion. The output is a single
`<review>` XML block (see `siege/parsers/review_xml.py` for the
exact schema). Score is 0-100; bands are 0-30 (rework), 31-60
(structural fixes), 61-85 (refinements), 86-100 (ready).

## Inputs

- `ref` — git ref
- `comp_id` — stable id of the scope

## Steps

1. **Read the draft state.** Call `mcp__siegeengine__get_state` to
   confirm the scope is in `drafted` status with a valid draft block.
   If it's already `reviewed` or `approved`, ask the user whether to
   re-review (most of the time this is a mistake).
2. **Fetch review context.** Call
   `mcp__siegeengine__get_review_context(ref=$ref, tier="feature_expansion",
   scope={"comp_id": $comp_id, "tier": "feature_expansion"}, draft_sha=<draft.body_sha256 from state>)`.
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
5. **Write the review** to `feature_expansion/$comp_id/review.md`.
6. **Materialize state JSON.** From the repo root, call the writer
   CLI. It extracts `<score>` and `<intro>` from the review with a
   lenient regex, computes the review sha256, writes the `review`
   block into `state/feature_expansion/$comp_id.json`, flips status
   to `reviewed`, and mints a fresh nonce:

   ```bash
   python3 -m siege.cli write-review \
     --tier feature_expansion \
     --comp-id "$comp_id" \
     --review-path "feature_expansion/$comp_id/review.md"
   ```

   It prints a JSON line with `state_path`, `score`, and
   `intro_first_sentence`. A non-zero exit means the review was
   rejected — `<score>` missing or out of the 0-100 range, `<intro>`
   missing or empty, or the scope not in `drafted` status. Fix the
   review (or re-fetch the scope) and re-run.
7. **Stage both files**, commit:
   `review(feature_expansion/$id): score=<N> — <intro first sentence>`
8. **Push.**

## Don't

- Don't review a scope that isn't `drafted` (without confirmation).
- Don't omit the `<intro>` or emit a non-integer `<score>`.
- Don't reuse a stale `draft_sha` — re-fetch state if you've been
  idle and someone might have re-drafted.

## Output

One line: `score=<N> — <intro first sentence>`, plus the commit sha.
