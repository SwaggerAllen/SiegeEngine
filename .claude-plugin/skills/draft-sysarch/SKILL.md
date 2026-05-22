---
name: draft-sysarch
description: Draft a sysarch section artifact. Reads context via the `siege` CLI for the scope, drafts the body, validates it, then commits state + body in one commit and pushes. Triggers when the user says "draft sysarch <id>", "/draft_sysarch <id>", or after `/scaffold` or `/run_tier sysarch` enumerates pending scopes.
thinking_effort: max
---

# Draft a sysarch section

You are drafting one sysarch section artifact end-to-end on the git-backed
substrate. The `siege` CLI gives you the context bundle the prompt
needs — a local projection of the committed tree, no server; you
compose the draft, validate it, materialize the state files
with the `siege` writer CLI, and commit + push exactly one commit
(artifact body, state JSON, and identity ledger together).

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)
- `comp_id` — stable id of the scope
- (optional) `prior_review_text` — non-empty when this is a regen pass

## Steps

1. **Fetch generation context.** From the repo root, run
   `python3 -m siege.cli get-context --tier sysarch --comp-id "$comp_id"`.
   It projects the committed tree at `HEAD` and prints the context
   bundle — instruction text + per-key inputs — as JSON on stdout.
2. **Compose the draft.** Use the bundle's instruction text and per-key
   inputs to produce the artifact body. Section headers must use the
   `## <prefix>:<name>` convention so the body section parser can pick
   them up downstream (see `docs/migration/state-schema.md` and
   `siege/fragments.py:section_for_kind`). This is a top-of-chain tier — use the deepest thinking budget you can.
3. **Write the body file** to `sysarch/$comp_id/body.md`.
4. **Materialize state JSON + identity ledger.** From the repo root,
   call the writer CLI. It computes the body sha256, mints a nonce,
   writes `state/sysarch/$comp_id.json`, and derives the slim identity
   ledger at `ids/sysarch/$comp_id.json` — one `comp_*` node per
   `<component>` the body declares (creating parent directories as
   needed). It carries `edges` / `meta` / `is_foundation` forward from
   any prior state, and carries `comp_*` ids forward by each
   component's `alias` from any prior ledger, so a regen keeps ids
   stable; a new or re-aliased component mints a fresh id:

   ```bash
   python3 -m siege.cli write-draft \
     --tier sysarch \
     --comp-id "$comp_id" \
     --body-path "sysarch/$comp_id/body.md" \
     --thinking-effort max \
     --batch-id "${batch_id:-}" \
     --prior-review-text "${prior_review_text:-}"
   ```

   It prints a JSON line with `state_path`, `ids_path`,
   `body_sha256`, and `node_count`. A non-zero exit means the body
   failed validation — treat the stderr as feedback, re-compose (step
   2), and retry (up to 3 times); if it still fails, stop and surface
   the errors. The ledger is the canonical list of components:
   `/run_tier comparch` enumerates the comparch scope set from it.
5. **Stage the body, state JSON, and ledger**, commit with message:
   `draft(sysarch/$id): <one-line summary>`
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
