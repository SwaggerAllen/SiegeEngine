---
name: mark-reviewed
description: Manually transition a scope's state to `reviewed` after an out-of-band review.md edit. Use only as a repair tool — normal reviews flow through the per-tier `review-*` skill which writes the file + state JSON together.
---

# Mark a scope as reviewed

Use this when a review.md was edited or written outside the
`review-<tier>` flow and the state JSON needs to catch up. Re-parses
the review to pull the score; if the review file isn't valid XML
per the parser contract, the skill stops and surfaces the parse
error so you can fix the file before retrying.

## Inputs

- `ref`, `tier`, `comp_id` (or `parent_id` + `sub_id`)

## Steps

1. Read the review file at the conventional `review.md` path.
2. Parse it via the review XML parser; extract `<score>`.
3. Read the existing state JSON. It must be in `drafted` status with
   a populated `draft` block — otherwise abort with the inconsistency.
4. Update:
   - `status` = `"reviewed"`
   - `review.body_path` = the review path
   - `review.body_sha256` = sha256 of the file bytes
   - `review.reviewed_at` = now
   - `review.score` = the parsed integer
   - Mint fresh nonce
5. Commit + push one commit:
   `mark-reviewed(<tier>/$id): score=<N>`

## Output

Commit sha + the score that landed.
