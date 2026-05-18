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

## Steps

1. Read the existing state JSON. It must be in `reviewed` status with
   a populated `review` block. If it's still `drafted`, run the
   review skill first; if it's already `approved`, this is a no-op.
2. Update:
   - `status` = `"approved"`
   - `approval.approved_at` = now
   - `approval.approved_by` = `$approver`
   - Mint fresh nonce
3. Commit + push one commit:
   `approve(<tier>/$id): by <approver>`

## Output

Commit sha + a one-line summary noting which downstream tiers now
unblock against this approval.
