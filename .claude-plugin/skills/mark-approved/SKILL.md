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

1. **Flip the state to approved.** From the repo root, call the
   writer CLI's `write-approval` subcommand. It requires the scope to
   be in `reviewed` status with a populated `review` block, then sets
   `status` to `approved`, stamps `approval.approved_at` +
   `approval.approved_by`, and mints a fresh nonce. `schema_version`
   and `scope.phase` are left untouched.

   ```bash
   APPROVER="${approver:-$(git config user.email)}"
   ARGS=(--tier "$tier" --approver "$APPROVER")
   [ -n "${comp_id:-}" ]   && ARGS+=(--comp-id "$comp_id")
   [ -n "${parent_id:-}" ] && ARGS+=(--parent-id "$parent_id")
   [ -n "${sub_id:-}" ]    && ARGS+=(--sub-id "$sub_id")
   [ -n "${phase:-}" ]     && ARGS+=(--phase "$phase")
   python3 -m siege.cli write-approval "${ARGS[@]}"
   ```

   It prints a JSON line with `state_path` and `approved_by`. A
   non-zero exit means the scope isn't in `reviewed` status — if it's
   still `drafted`, run the review skill first; if it's already
   `approved`, there's nothing to do.
2. **Commit + push one commit:**
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
`scope.phase = N`; the CLI preserves both.

## Output

Commit sha + a one-line summary noting which downstream tiers now
unblock against this approval.
