---
name: draft-fanin
description: Draft a fan-in synthesis artifact. Reads `get_generation_context` for the scope, drafts the body, validates it, then commits state + body in one commit and pushes. Triggers when the user says "draft fanin <id>", "/draft_fanin <id>", or after `/scaffold` or `/run_tier fanin` enumerates pending scopes.
thinking_effort: default
---

# Draft a fan-in synthesis

You are drafting one fan-in synthesis artifact end-to-end on the git-backed
substrate. The MCP server gives you the bundle of context the prompt
needs; you compose the draft, validate it, and commit + push exactly
one commit (artifact body + state JSON together).

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)
- `comp_id` — stable id of the scope
- (optional) `prior_review_text` — non-empty when this is a regen pass

## Steps

1. **Fetch generation context.** Call
   `mcp__siegeengine__get_generation_context(ref=$ref, tier="fanin", scope={"comp_id": $comp_id, "tier": "fanin"})`.
2. **Compose the draft.** Use the bundle's instruction text and per-key
   inputs to produce the artifact body. Section headers must use the
   `## <prefix>:<name>` convention so the body section parser can pick
   them up downstream (see `docs/migration/state-schema.md` and
   `siege_mcp/fragments.py:section_for_kind`). Use default thinking budget; the handles upstream of you carry the load.
3. **Validate.** Call `mcp__siegeengine__validate_artifact(ref=$ref, tier="fanin", scope=..., body=<draft>)`.
   If `ok` is false, treat the errors as feedback and re-run step 2
   (loop up to 3 times). If still failing, stop and surface the errors.
4. **Write the body file** to `fanin/$comp_id/body.md`.
5. **Update or create the state JSON** at `state/fanin/$comp_id.json`:
   - Set `status` to `"drafted"`
   - Set `draft.body_path`, `draft.body_sha256` (sha256 of the body bytes),
     `draft.generated_at` (UTC ISO-8601), `draft.generator_metadata`
     (carry `thinking_effort` + `batch_id` if running under one),
     `draft.prior_review_text` (if any)
   - Mint a fresh ULID-shaped `nonce`
   - Carry forward `edges` + `meta` if present, otherwise emit empty
     blocks
6. **Stage both files**, commit with message:
   `draft(fanin/$id): <one-line summary>`
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
