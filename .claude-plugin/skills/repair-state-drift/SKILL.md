---
name: repair-state-drift
description: Recompute body_sha256 for a scope's state JSON when its body has drifted. Use when `get-state` returns a `drift` block on a scope you trust the body of — this skill writes a new state JSON with the correct sha and bumps nonce.
---

# Repair state JSON drift

Drift means the state JSON's recorded `body_sha256` doesn't match the
actual sha256 of the body file's bytes on the ref. This usually means
a body was edited without re-running the draft skill (or a merge
created a divergent body without a state update). The repair is to
recompute the sha and write a new state JSON; for the single-node arch
tiers (`feature_expansion`, `requirements`) it also rebuilds the
derived node manifest, which the same body edit left stale.

## Inputs

- `ref`, `tier`, `comp_id` (or `parent_id` + `sub_id`)
- (optional) `phase` — required to locate a phased `impl` / `fanin`
  node's state JSON; see "Phased nodes" below. Omit for arch tiers.
- (optional) `expected_status` — if set, the skill refuses to repair
  when the state's status doesn't match. Defaults to no check.

## Steps

1. **Status pre-check.** Read the state JSON at the conventional path
   (for a phased impl/fanin node use the `p<N>` layout below). If
   `expected_status` is set and `status` doesn't match, abort. If
   `status` is `approved`, stop and ask the user to confirm before
   continuing — drift on an approved artifact usually means something
   more serious is wrong (see "Don't").
2. **Repair.** From the repo root, call the writer CLI's
   `repair-drift` subcommand. It reads the state, recomputes the
   `body_sha256` of the draft body (and the review body, if a review
   block is present) from the paths the state itself records, bumps
   the nonce when anything changed, and for the decomposing tiers
   (feature_expansion / requirements / sysarch / comparch) re-derives
   the identity ledger from the trusted body (ids carry forward by
   name or alias). It leaves `schema_version`, `scope.phase`, and
   every other field untouched.

   ```bash
   ARGS=(--tier "$tier")
   [ -n "${comp_id:-}" ]   && ARGS+=(--comp-id "$comp_id")
   [ -n "${parent_id:-}" ] && ARGS+=(--parent-id "$parent_id")
   [ -n "${sub_id:-}" ]    && ARGS+=(--sub-id "$sub_id")
   [ -n "${phase:-}" ]     && ARGS+=(--phase "$phase")
   python3 -m siege.cli repair-drift "${ARGS[@]}"
   ```

   It prints a JSON line: `changed` (true/false), the per-file sha
   `deltas` when it changed, and `ledger_rebuilt`.
3. **Commit one commit.** Stage the state JSON and, for the
   ledger-deriving tiers, the identity ledger. If `git status` then
   shows no staged changes, nothing actually drifted — report that and
   stop without committing. Otherwise commit:
   `repair(<tier>/$id): recompute body_sha256 (drift)`
4. **Push.**

## Phased nodes

When `tier` is `impl` or `fanin` and the node is phased, supply the
`phase` input — the state JSON lives at a `p<N>` path:

| tier  | unphased state path | phased (`phase=N`) state path |
|-------|---------------------|--------------------------------|
| impl  | `state/impl/<parent>/<sub>.json` | `state/impl/<parent>/pN/<sub>.json` |
| fanin | `state/fanin/<comp>.json` | `state/fanin/<comp>/pN.json` |

## Don't

- Don't repair drift on an `approved` scope without explicit user
  confirmation — drift on an approved artifact usually means
  something more serious is wrong (a merge that mangled content)
  and silently recomputing the sha papers over it.

## Output

What changed (old sha → new sha for each file) + commit sha.
