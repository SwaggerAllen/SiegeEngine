---
name: review-fanin
description: Review a fan-in synthesis draft. Reads context via the `siege` CLI, produces a `<review>` XML block per the parser contract, writes it as review.md, updates state JSON, commits, and pushes. Triggers automatically after a `draft-fanin` or on manual `/review_fanin <id>`.
thinking_effort: default
---

# Review a fan-in synthesis

You are reviewing one drafted fan-in synthesis. The output is a single
`<review>` XML block (see `siege/parsers/review_xml.py` for the
exact schema). Score is 0-100; bands are 0-30 (rework), 31-60
(structural fixes), 61-85 (refinements), 86-100 (ready).

## Inputs

- `ref` — git ref
- `comp_id` — stable id of the scope
- (optional) `phase` — phase index for a phased fan-in node; omit for
  an unphased (legacy) fan-in. Must match the `phase` the node was
  drafted at, or `get-state` / the paths below address the wrong node.

## Steps

1. **Read the draft state.** From the repo root, run
   `python3 -m siege.cli get-state --tier fanin --comp-id "$comp_id" ${phase:+--phase "$phase"}`
   (the `${phase:+…}` expands to nothing for an unphased fan-in).
   Confirm `status` is `drafted` with a populated `draft` block; keep
   the `draft.body_sha256` for step 2. If `status` is `reviewed` or
   `approved`, ask the user whether to re-review (most of the time
   this is a mistake).
2. **Fetch review context.** Run `python3 -m siege.cli
   get-review-context --tier fanin --comp-id "$comp_id"
   ${phase:+--phase "$phase"} --draft-sha <draft.body_sha256 from
   step 1>`. The `--draft-sha` guards against reviewing a stale
   draft. It prints the review context bundle as JSON on stdout.
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
   `fanin/$comp_id/p$phase/review.md`; unphased → `fanin/$comp_id/review.md`.
6. **Materialize state JSON.** From the repo root, call the writer
   CLI. The bash computes the phased vs unphased review path from
   `$phase` and passes `--phase` only when the node is phased; the
   CLI extracts `<score>` and `<intro>`, computes the review sha256,
   writes the `review` block, flips status to `reviewed`, and mints a
   fresh nonce:

   ```bash
   PHASE="${phase:-}"
   if [ -n "$PHASE" ]; then
     REVIEW_PATH="fanin/$comp_id/p$PHASE/review.md"
     PHASE_ARG=(--phase "$PHASE")
   else
     REVIEW_PATH="fanin/$comp_id/review.md"
     PHASE_ARG=()
   fi
   python3 -m siege.cli write-review \
     --tier fanin \
     --comp-id "$comp_id" \
     "${PHASE_ARG[@]}" \
     --review-path "$REVIEW_PATH"
   ```

   It prints a JSON line with `state_path`, `score`, and
   `intro_first_sentence`. A non-zero exit means the review was
   rejected — `<score>` missing or out of the 0-100 range, `<intro>`
   missing or empty, or the scope not in `drafted` status. Fix the
   review (or re-fetch the scope) and re-run.
7. **Stage both files**, commit:
   `review(fanin/$id): score=<N> — <intro first sentence>`
8. **Push.**

## Don't

- Don't review a scope that isn't `drafted` (without confirmation).
- Don't omit the `<intro>` or emit a non-integer `<score>`.
- Don't reuse a stale `draft_sha` — re-fetch state if you've been
  idle and someone might have re-drafted.

## Output

One line: `score=<N> — <intro first sentence>`, plus the commit sha.
