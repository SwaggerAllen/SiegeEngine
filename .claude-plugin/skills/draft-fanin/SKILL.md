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
- (optional) `phase` — phase index for a phased fan-in node. Set it
  when the project is phased (`/run_phase` drives fan-in per phase);
  omit it for an unphased (legacy) fan-in. A phased node lands at the
  `p<N>` path layout and carries schema v2.
- (optional) `prior_review_text` — non-empty when this is a regen pass

## Steps

1. **Fetch generation context.** Call
   `mcp__siegeengine__get_generation_context(ref=$ref, tier="fanin", comp_id=$comp_id, phase=$phase)`
   (omit `phase` entirely for an unphased fan-in). When `phase` is
   set, the bundle's `impl_bodies` is the cumulative phase-≤N slice —
   every impl node at phase ≤ N, deduped per subcomponent.
2. **Compose the draft.** Use the bundle's instruction text and per-key
   inputs to produce the artifact body. Section headers must use the
   `## <prefix>:<name>` convention so the body section parser can pick
   them up downstream (see `docs/migration/state-schema.md` and
   `siege_mcp/fragments.py:section_for_kind`). Use default thinking budget; the handles upstream of you carry the load.
3. **Validate.** Call `mcp__siegeengine__validate_artifact(ref=$ref, tier="fanin", scope=..., body=<draft>)`.
   If `ok` is false, treat the errors as feedback and re-run step 2
   (loop up to 3 times). If still failing, stop and surface the errors.
4. **Write the body file.** Phased node (`phase` set) →
   `fanin/$comp_id/p$phase/body.md`; unphased → `fanin/$comp_id/body.md`.
5. **Materialize state JSON inline** (no external Python package
   needed — pure `python3` from stdlib, which any environment CC
   runs in has). The bash computes the phased vs unphased paths from
   `$phase`; the python stamps schema v2 + `scope.phase` for a phased
   node, v1 + `phase: null` otherwise:

   ```bash
   COMP_ID="$comp_id"
   PHASE="${phase:-}"
   if [ -n "$PHASE" ]; then
     BODY_PATH=fanin/$COMP_ID/p$PHASE/body.md
     STATE_PATH=state/fanin/$COMP_ID/p$PHASE.json
   else
     BODY_PATH=fanin/$COMP_ID/body.md
     STATE_PATH=state/fanin/$COMP_ID.json
   fi
   THINKING=default
   PRIOR_REVIEW_TEXT="${prior_review_text:-}"
   BATCH_ID="${batch_id:-}"
   mkdir -p "$(dirname "$STATE_PATH")"
   python3 - "$BODY_PATH" "$STATE_PATH" "$THINKING" "$PRIOR_REVIEW_TEXT" "$BATCH_ID" "$COMP_ID" "$PHASE" <<'PY'
import hashlib, json, os, secrets, sys, time

body_path, state_path, thinking, prior_review, batch_id = sys.argv[1:6]
comp_id, phase_raw = sys.argv[6:8]
phase = int(phase_raw) if phase_raw else None
scope = {"tier": "fanin", "comp_id": comp_id, "parent_id": None, "sub_id": None, "phase": phase}

body = open(body_path, "rb").read()
sha = hashlib.sha256(body).hexdigest()
nonce_bits = secrets.randbits(128)
alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
nonce = "".join(reversed([alphabet[(nonce_bits >> (5*i)) & 0x1F] for i in range(26)]))

prior = {}
if os.path.exists(state_path):
    prior = json.loads(open(state_path).read())
state = {
    "schema_version": 2 if phase is not None else 1,
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
