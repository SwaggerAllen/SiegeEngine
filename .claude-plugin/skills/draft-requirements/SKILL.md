---
name: draft-requirements
description: Draft a requirements artifact. Reads `get_generation_context` for the scope, drafts the body, validates it, then commits state + body in one commit and pushes. Triggers when the user says "draft requirements <id>", "/draft_requirements <id>", or after `/scaffold` or `/run_tier requirements` enumerates pending scopes.
thinking_effort: max
---

# Draft a requirements

You are drafting one requirements artifact end-to-end on the git-backed
substrate. The MCP server gives you the bundle of context the prompt
needs; you compose the draft, validate it, materialize the state files
with the `siege` writer CLI, and commit + push exactly one commit
(artifact body, state JSON, and node manifest together).

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)
- `comp_id` — stable id of the scope
- (optional) `prior_review_text` — non-empty when this is a regen pass

## Steps

1. **Fetch generation context.** Call
   `mcp__siegeengine__get_generation_context(ref=$ref, tier="requirements", scope={"comp_id": $comp_id, "tier": "requirements"})`.
2. **Compose the draft.** Use the bundle's instruction text and per-key
   inputs to produce the artifact body. Section headers must use the
   `## <prefix>:<name>` convention so the body section parser can pick
   them up downstream (see `docs/migration/state-schema.md` and
   `siege/fragments.py:section_for_kind`). This is a top-of-chain tier — use the deepest thinking budget you can.
3. **Validate.** Call `mcp__siegeengine__validate_artifact(ref=$ref, tier="requirements", scope=..., body=<draft>)`.
   If `ok` is false, treat the errors as feedback and re-run step 2
   (loop up to 3 times). If still failing, stop and surface the errors.
4. **Write the body file** to `requirements/$comp_id/body.md`.
5. **Materialize state JSON + node manifest.** From the repo root,
   call the writer CLI. It computes the body sha256, mints a nonce,
   writes `state/requirements/$comp_id.json`, and derives the node
   manifest at `manifest/requirements/$comp_id.json` (creating parent
   directories as needed). It carries `edges` / `meta` /
   `is_foundation` forward from any prior state, and carries `resp_*`
   node ids forward by name from any prior manifest, so a regen keeps
   ids stable; a new or renamed responsibility mints a fresh id:

   ```bash
   python3 -m siege.cli write-draft \
     --tier requirements \
     --comp-id "$comp_id" \
     --body-path "requirements/$comp_id/body.md" \
     --thinking-effort max \
     --batch-id "${batch_id:-}" \
     --prior-review-text "${prior_review_text:-}"
   ```

   It prints a JSON line with `state_path`, `manifest_path`,
   `body_sha256`, and `node_count`. A non-zero exit means the body
   failed validation — treat the stderr as feedback and loop back to
   step 2. The manifest is the node index the sysarch / phasing /
   related-features readers consume — see
   `docs/migration/state-schema.md`.
6. **Stage the body, state JSON, and manifest**, commit with message:
   `draft(requirements/$id): <one-line summary>`
7. **Push** with `git push -u origin $ref` (retry on network failure
   up to 4 times with 2s / 4s / 8s / 16s backoff).

## Don't

- Don't overwrite an existing **approved** draft without explicit
  user confirmation. If `status` is `approved`, abort.
- Don't commit a body that fails `validate_artifact`. Loop or stop.
- Don't push to any branch other than `$ref`.
- Don't create a PR.

## Output

One line summarizing what was drafted + the commit sha.
