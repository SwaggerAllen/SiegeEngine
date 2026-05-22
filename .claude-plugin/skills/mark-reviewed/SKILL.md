---
name: mark-reviewed
description: Manually transition a scope's state to `reviewed` after an out-of-band review.md edit. Use only as a repair tool — normal reviews flow through the per-tier `review-*` skill which writes the file + state JSON together.
---

# Mark a scope as reviewed

Use this when a review.md was edited or written outside the
`review-<tier>` flow and the state JSON needs to catch up. The writer
CLI re-parses the review to pull the score; if the review file is
missing a usable `<score>` or `<intro>`, the CLI stops and surfaces
the error so you can fix the file before retrying.

## Inputs

- `ref`, `tier`, `comp_id` (or `parent_id` + `sub_id`)
- (optional) `phase` — required for a phased `impl` / `fanin` node;
  see "Phased nodes" below. Omit for the five arch tiers.

## Steps

1. **Re-sync the state JSON.** From the repo root, call the writer
   CLI's `write-review` subcommand. It extracts `<score>` and
   `<intro>` from the review file with a lenient regex, computes the
   review sha256, writes the `review` block, flips `status` to
   `reviewed`, and mints a fresh nonce. It refuses to run unless the
   scope is currently in `drafted` status with a populated `draft`
   block. `schema_version` and `scope.phase` are left untouched.

   Set the scope vars per the tier, resolve the conventional
   `review.md` path, then call the CLI:

   ```bash
   case "$tier" in
     subcomparch) REVIEW_PATH="subcomparch/$parent_id/subs/$sub_id/review.md" ;;
     impl)
       if [ -n "${phase:-}" ]; then REVIEW_PATH="impl/$parent_id/subs/$sub_id/p$phase/review.md"
       else REVIEW_PATH="impl/$parent_id/subs/$sub_id/review.md"; fi ;;
     fanin)
       if [ -n "${phase:-}" ]; then REVIEW_PATH="fanin/$comp_id/p$phase/review.md"
       else REVIEW_PATH="fanin/$comp_id/review.md"; fi ;;
     *) REVIEW_PATH="$tier/$comp_id/review.md" ;;
   esac
   ARGS=(--tier "$tier" --review-path "$REVIEW_PATH")
   [ -n "${comp_id:-}" ]   && ARGS+=(--comp-id "$comp_id")
   [ -n "${parent_id:-}" ] && ARGS+=(--parent-id "$parent_id")
   [ -n "${sub_id:-}" ]    && ARGS+=(--sub-id "$sub_id")
   [ -n "${phase:-}" ]     && ARGS+=(--phase "$phase")
   python3 -m siege.cli write-review "${ARGS[@]}"
   ```

   It prints a JSON line with `state_path`, `score`, and
   `intro_first_sentence`. A non-zero exit means the review is
   missing a usable `<score>` / `<intro>`, or the scope isn't in
   `drafted` status — fix the file (or the scope) and retry.
2. **Commit + push one commit:**
   `mark-reviewed(<tier>/$id): score=<N>`

## Phased nodes

When `tier` is `impl` or `fanin` and the node is phased, supply the
`phase` input — the node is keyed by `phase` and the on-disk layout
differs from the unphased (legacy) one:

| tier  | unphased state · body | phased (`phase=N`) state · body |
|-------|-----------------------|----------------------------------|
| impl  | `state/impl/<parent>/<sub>.json` · `impl/<parent>/subs/<sub>/body.md` | `state/impl/<parent>/pN/<sub>.json` · `impl/<parent>/subs/<sub>/pN/body.md` |
| fanin | `state/fanin/<comp>.json` · `fanin/<comp>/body.md` | `state/fanin/<comp>/pN.json` · `fanin/<comp>/pN/body.md` |

`review.md` sits beside `body.md`. A phased node's state JSON carries
`schema_version: 2` and `scope.phase = N`; the CLI preserves both.

## Output

Commit sha + the score that landed.
