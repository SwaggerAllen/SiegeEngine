---
name: mark-drafted
description: Manually transition a scope's state to `drafted` after an out-of-band body edit. Use only when you've hand-edited a body.md file and need to re-sync state JSON (recompute body_sha256, bump nonce, set status). For normal drafts, use the per-tier `draft-*` skill instead — this is a repair tool.
---

# Mark a scope as drafted

Use this when you've manually edited a body.md outside of a `draft-*`
skill flow and need to bring state JSON back in sync. Normal drafts
should go through `draft-<tier>` which mints the state JSON for you.

## Inputs

- `ref` — git ref
- `tier` — one of feature_expansion / requirements / sysarch / comparch
  / subcomparch / impl / fanin
- `comp_id` and/or `parent_id` + `sub_id` per the tier's scope shape

## Steps

1. Locate the body at the conventional path
   (`<tier>/$comp_id/body.md` or `<tier>/$parent_id/subs/$sub_id/body.md`).
2. Compute `body_sha256` of the file contents.
3. Read the existing state JSON at the conventional state path.
4. Update:
   - `status` = `"drafted"`
   - `draft.body_sha256` = the new hash
   - `draft.generated_at` = now (UTC ISO-8601)
   - Mint a fresh `nonce`
   - Clear `review` and `approval` blocks (they no longer apply)
5. Commit + push one commit:
   `mark-drafted(<tier>/$id): manual body edit`

## Output

Commit sha + one-line summary of what changed in the state JSON.
