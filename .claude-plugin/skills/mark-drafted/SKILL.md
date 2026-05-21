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

1. **Re-sync the state JSON.** From the repo root, call the writer
   CLI's `mark-drafted` subcommand. It reads the existing state,
   recomputes `body_sha256` from the body file the state already
   points at, sets a fresh `generated_at`, mints a new nonce, flips
   `status` back to `drafted`, and clears the `review` / `approval`
   blocks. For `feature_expansion` / `requirements` it also
   re-derives the node manifest from the edited body (a hand edit can
   add, remove, or rename nodes — ids carry forward by name). It
   leaves `schema_version` and `scope.phase` exactly as they were.

   Set the scope vars per the tier, then call the CLI — the args
   array picks up only the keys the tier uses:

   ```bash
   ARGS=(--tier "$tier")
   [ -n "${comp_id:-}" ]   && ARGS+=(--comp-id "$comp_id")
   [ -n "${parent_id:-}" ] && ARGS+=(--parent-id "$parent_id")
   [ -n "${sub_id:-}" ]    && ARGS+=(--sub-id "$sub_id")
   [ -n "${phase:-}" ]     && ARGS+=(--phase "$phase")
   python3 -m siege.cli mark-drafted "${ARGS[@]}"
   ```

   It prints a JSON line with `state_path`, `body_sha256`, and — for
   the manifest-deriving tiers — `manifest_path` + `node_count`. A
   non-zero exit means the scope has no existing state with a draft
   block, or the body file it points at is missing.
2. **Commit + push one commit** — stage the state JSON and, when the
   CLI rebuilt one, the manifest:
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
`schema_version: 2` and `scope.phase = N`; the CLI preserves both.

## Output

Commit sha + one-line summary of what changed in the state JSON.
