---
name: review-sysarch
description: Review a sysarch section draft. Reads `get_review_context` for the scope, produces a `<review>` XML block per the parser contract, writes it as review.md, updates state JSON, commits, and pushes. Triggers automatically after a `draft-sysarch` or on manual `/review_sysarch <id>`.
thinking_effort: max
---

# Review a sysarch section

You are reviewing one drafted sysarch section. The output is a single
`<review>` XML block (see `siege_mcp/parsers/review_xml.py` for the
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
   `mcp__siegeengine__get_review_context(ref=$ref, tier="sysarch",
   scope={"comp_id": $comp_id, "tier": "sysarch"}, draft_sha=<draft.body_sha256 from state>)`.
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
5. **Write the review** to `sysarch/$comp_id/review.md`.
6. **Update state JSON** at `state/sysarch/$comp_id.json`:
   - Set `status` to `"reviewed"`
   - Set `review.body_path`, `review.body_sha256`, `review.reviewed_at`,
     `review.score` (extract from `<score>`), `review.reviewer_metadata`
   - Bump `nonce`
7. **Stage both files**, commit:
   `review(sysarch/$id): score=<N> — <intro first sentence>`
8. **Push.**

## Don't

- Don't review a scope that isn't `drafted` (without confirmation).
- Don't omit the `<intro>` or emit a non-integer `<score>`.
- Don't reuse a stale `draft_sha` — re-fetch state if you've been
  idle and someone might have re-drafted.

## Output

One line: `score=<N> — <intro first sentence>`, plus the commit sha.
