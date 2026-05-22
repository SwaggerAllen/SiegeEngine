---
name: draft-fanin
description: Draft a fan-in synthesis artifact. Reads context via the `siege` CLI for the scope, drafts the body, validates it, then commits state + body in one commit and pushes. Triggers when the user says "draft fanin <id>", "/draft_fanin <id>", or after `/scaffold` or `/run_tier fanin` enumerates pending scopes.
thinking_effort: default
---

# Draft a fan-in synthesis

You are drafting one fan-in synthesis artifact end-to-end on the git-backed
substrate. The `siege` CLI gives you the context bundle the prompt
needs — a local projection of the committed tree, no server; you
compose the draft, validate it, materialize the state JSON
with the `siege` writer CLI, and commit + push exactly one commit
(artifact body and state JSON together).

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)
- `comp_id` — stable id of the scope
- (optional) `phase` — phase index for a phased fan-in node. Set it
  when the project is phased (`/run_phase` drives fan-in per phase);
  omit it for an unphased (legacy) fan-in. A phased node lands at the
  `p<N>` path layout and carries schema v2.
- (optional) `prior_review_text` — non-empty when this is a regen pass

## Steps

1. **Fetch generation context.** From the repo root, run
   `python3 -m siege.cli get-context --tier fanin --comp-id "$comp_id" ${phase:+--phase "$phase"}`
   (the `${phase:+…}` expands to nothing for an unphased fan-in). It
   projects the committed tree at `HEAD` and prints the context bundle
   — instruction text + per-key inputs — as JSON on stdout. When
   `phase` is set, the bundle's `impl_bodies` is the cumulative
   phase-≤N slice — every impl node at phase ≤ N, deduped per
   subcomponent.
2. **Compose the draft.** Use the bundle's instruction text and per-key
   inputs to produce the artifact body. Section headers must use the
   `## <prefix>:<name>` convention so the body section parser can pick
   them up downstream (see `docs/migration/state-schema.md` and
   `siege/fragments.py:section_for_kind`). Use default thinking budget; the handles upstream of you carry the load.
3. **Write the body file.** Phased node (`phase` set) →
   `fanin/$comp_id/p$phase/body.md`; unphased → `fanin/$comp_id/body.md`.
4. **Materialize state JSON.** From the repo root, call the writer
   CLI. The bash computes the phased vs unphased body path from
   `$phase` and passes `--phase` only when the node is phased; the
   CLI stamps schema v2 + `scope.phase` for a phased node, v1
   otherwise, and carries `edges` / `meta` / `is_foundation` forward
   from any prior state:

   ```bash
   PHASE="${phase:-}"
   if [ -n "$PHASE" ]; then
     BODY_PATH="fanin/$comp_id/p$PHASE/body.md"
     PHASE_ARG=(--phase "$PHASE")
   else
     BODY_PATH="fanin/$comp_id/body.md"
     PHASE_ARG=()
   fi
   python3 -m siege.cli write-draft \
     --tier fanin \
     --comp-id "$comp_id" \
     "${PHASE_ARG[@]}" \
     --body-path "$BODY_PATH" \
     --thinking-effort default \
     --batch-id "${batch_id:-}" \
     --prior-review-text "${prior_review_text:-}"
   ```

   It prints a JSON line with `state_path` and `body_sha256`. A
   non-zero exit means the body failed validation — treat the stderr
   as feedback, re-compose (step 2), and retry (up to 3 times); if it
   still fails, stop and surface the errors.
5. **Stage both files**, commit with message:
   `draft(fanin/$id): <one-line summary>`
6. **Push** with `git push -u origin $ref` (retry on network failure
   up to 4 times with 2s / 4s / 8s / 16s backoff).

## Don't

- Don't overwrite an existing **approved** draft without explicit
  user confirmation. If `status` is `approved`, abort.
- Don't commit a body the CLI rejected — `write-draft` exits non-zero
  on a validation failure.
- Don't push to any branch other than `$ref`.
- Don't create a PR.

## Output

One line summarizing what was drafted + the commit sha.
