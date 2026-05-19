---
name: draft-comparch
description: Draft a comparch artifact. Reads `get_generation_context` for the scope, drafts the body, validates it, then commits state + body in one commit and pushes. Triggers when the user says "draft comparch <id>", "/draft_comparch <id>", or after `/scaffold` or `/run_tier comparch` enumerates pending scopes.
thinking_effort: max
---

# Draft a comparch

You are drafting one comparch artifact end-to-end on the git-backed
substrate. The MCP server gives you the bundle of context the prompt
needs; you compose the draft, validate it, and commit + push exactly
one commit (artifact body + state JSON together).

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)
- `comp_id` — stable id of the scope
- (optional) `prior_review_text` — non-empty when this is a regen pass

## Steps

1. **Fetch generation context.** Call
   `mcp__siegeengine__get_generation_context(ref=$ref, tier="comparch", scope={"comp_id": $comp_id, "tier": "comparch"})`.
2. **Compose the draft.** Use the bundle's instruction text and per-key
   inputs to produce the artifact body. Section headers must use the
   `## <prefix>:<name>` convention so the body section parser can pick
   them up downstream (see `docs/migration/state-schema.md` and
   `siege_mcp/fragments.py:section_for_kind`). This is a top-of-chain tier — use the deepest thinking budget you can.
3. **Validate.** Call `mcp__siegeengine__validate_artifact(ref=$ref, tier="comparch", scope=..., body=<draft>)`.
   If `ok` is false, treat the errors as feedback and re-run step 2
   (loop up to 3 times). If still failing, stop and surface the errors.
4. **Write the body file** to `comparch/$comp_id/body.md`.
5. **Materialize state JSON inline** (no external Python package
   needed — pure `python3` from stdlib, which any environment CC
   runs in has). Pass the scope keys as positional args; the rest
   comes from env vars:

   ```bash
   COMP_ID="$comp_id"
   BODY_PATH=comparch/$comp_id/body.md
   STATE_PATH=state/comparch/$comp_id.json
   THINKING=max
   PRIOR_REVIEW_TEXT="${prior_review_text:-}"
   BATCH_ID="${batch_id:-}"
   mkdir -p "$(dirname "$STATE_PATH")"
   python3 - "$BODY_PATH" "$STATE_PATH" "$THINKING" "$PRIOR_REVIEW_TEXT" "$BATCH_ID" "$COMP_ID" <<'PY'
import hashlib, json, os, secrets, sys, time

body_path, state_path, thinking, prior_review, batch_id = sys.argv[1:6]
comp_id = sys.argv[6]
scope = {"tier": "comparch", "comp_id": comp_id, "parent_id": None, "sub_id": None}

body = open(body_path, "rb").read()
sha = hashlib.sha256(body).hexdigest()
nonce_bits = secrets.randbits(128)
alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
nonce = "".join(reversed([alphabet[(nonce_bits >> (5*i)) & 0x1F] for i in range(26)]))

prior = {}
if os.path.exists(state_path):
    prior = json.loads(open(state_path).read())
state = {
    "schema_version": 1,
    "scope": scope,
    "status": "drafted",
    "nonce": nonce,
    "is_foundation": prior.get("is_foundation", False),
    "draft": {
        "body_path": body_path,
        "body_sha256": sha,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator_metadata": {"thinking_effort": thinking, "batch_id": batch_id},
        "prior_review_text": prior_review,
    },
    "edges": prior.get("edges", {}),
    "meta": prior.get("meta", {}),
}
open(state_path, "w").write(json.dumps(state, indent=2, sort_keys=True) + "\n")
print(json.dumps({"state_path": state_path, "body_sha256": sha}))
PY
   ```

   The sha is from the canonical body bytes; the nonce is a 26-char
   base32-shaped ULID-ish string. Carries forward `edges` + `meta` +
   `is_foundation` from the prior state if any.
6. **Stage both files**, commit with message:
   `draft(comparch/$id): <one-line summary>`
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
