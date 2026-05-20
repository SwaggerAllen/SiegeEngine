---
name: mark-approved
description: Approve a reviewed scope. Updates state JSON to `approved` with the approver identity + timestamp. The only state transition that can't be undone by the next draft pass (downstream tiers read approved-only context).
---

# Approve a scope

Approval is the gate downstream tiers read. Once approved, the scope's
artifact body + state are the canonical version that everything below
it consumes. Re-approval after a regen is allowed (state goes back
through `drafted → reviewed → approved`), but skipping `reviewed` and
jumping straight to `approved` is a no.

## Inputs

- `ref`, `tier`, `comp_id` (or `parent_id` + `sub_id`)
- `approver` — username or email (defaults to git config user.email)
- (optional) `phase` — required for a phased `impl` / `fanin` node;
  see "Phased nodes" below. Omit for the five arch tiers.

## Steps

1. Read the existing state JSON at the conventional state path (for a
   phased impl/fanin node use the `p<N>` layout below). It must be in
   `reviewed` status with a populated `review` block. If it's still
   `drafted`, run the review skill first; if it's already `approved`,
   this is a no-op.
2. Update:
   - `status` = `"approved"`
   - `approval.approved_at` = now
   - `approval.approved_by` = `$approver`
   - Mint fresh nonce
   - Leave `schema_version` and `scope.phase` exactly as they are.
3. Commit + push one commit:
   `approve(<tier>/$id): by <approver>`

## Phased nodes

When `tier` is `impl` or `fanin` and the node is phased, supply the
`phase` input — the node is keyed by `phase` and its state JSON lives
at a `p<N>` path:

| tier  | unphased state path | phased (`phase=N`) state path |
|-------|---------------------|--------------------------------|
| impl  | `state/impl/<parent>/<sub>.json` | `state/impl/<parent>/pN/<sub>.json` |
| fanin | `state/fanin/<comp>.json` | `state/fanin/<comp>/pN.json` |

A phased node's state JSON carries `schema_version: 2` and
`scope.phase = N` — preserve both.

## Output

Commit sha + a one-line summary noting which downstream tiers now
unblock against this approval.
