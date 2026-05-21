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
- (optional) `phase` — required for a phased `impl` / `fanin` node;
  see "Phased nodes" below. Omit for the five arch tiers.

## Steps

1. Locate the body at the conventional path
   (`<tier>/$comp_id/body.md` or `<tier>/$parent_id/subs/$sub_id/body.md`;
   for a phased impl/fanin node use the `p<N>` layout below).
2. Compute `body_sha256` of the file contents.
3. Read the existing state JSON at the conventional state path.
4. Update:
   - `status` = `"drafted"`
   - `draft.body_sha256` = the new hash
   - `draft.generated_at` = now (UTC ISO-8601)
   - Mint a fresh `nonce`
   - Clear `review` and `approval` blocks (they no longer apply)
   - Leave `schema_version` and `scope.phase` exactly as they are.
5. Commit + push one commit:
   `mark-drafted(<tier>/$id): manual body edit`

## Phased nodes

When `tier` is `impl` or `fanin` and the node is phased, supply the
`phase` input — the node is keyed by `phase` and the on-disk layout
differs from the unphased (legacy) one:

| tier  | unphased state · body | phased (`phase=N`) state · body |
|-------|-----------------------|----------------------------------|
| impl  | `state/impl/<parent>/<sub>.json` · `impl/<parent>/subs/<sub>/body.md` | `state/impl/<parent>/pN/<sub>.json` · `impl/<parent>/subs/<sub>/pN/body.md` |
| fanin | `state/fanin/<comp>.json` · `fanin/<comp>/body.md` | `state/fanin/<comp>/pN.json` · `fanin/<comp>/pN/body.md` |

`review.md` sits beside `body.md`. A phased node's state JSON carries
`schema_version: 2` and `scope.phase = N` — preserve both.

## Output

Commit sha + one-line summary of what changed in the state JSON.
