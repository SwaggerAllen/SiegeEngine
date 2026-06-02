---
name: remove-feature
description: Delete a feature from the feature_expansion substrate body. Mechanical, no LLM — wraps `siege remove-feature`. Use when the user says "remove feature X", "drop feature X", or "/remove_feature X". Identifies the target by either `feat_id` (resolved through the ledger) or `name` (matched against the body's `<name>` text).
---

# Remove a feature

The mechanical inverse of `add-feature`. Deletes one `<feature>` block
from the feature_expansion body, drops it from the slim identity
ledger, and flips state back to `drafted`. The downstream tiers that
referenced the dropped feature (requirements responsibilities with a
`<feat>` ref to it, sysarch components claiming it) go stale — but
this skill does not propagate; that's the user's call.

## Inputs

- Exactly one of:
  - `feat_id` — stable `feat_*` id, resolved through
    `ids/feature_expansion/$comp_id.json`
  - `name` — the body's `<name>` text, matched case-insensitively
- (optional) `comp_id` — substrate-root scope (default: `proj`)

## Steps

1. **Run the CLI subcommand.** From the repo root, pass exactly one
   identifier:

   ```bash
   ARGS=()
   [ -n "${feat_id:-}" ] && ARGS+=(--feat-id "$feat_id")
   [ -n "${name:-}" ]    && ARGS+=(--name "$name")
   python3 -m siege.cli remove-feature "${ARGS[@]}"
   ```

   The CLI looks up the matching `<feature>` block, deletes it (with
   surrounding whitespace), re-derives the ledger (the orphan ledger
   entry is silently dropped — that's by design), and re-syncs state
   to `drafted`. A non-zero exit means: id not found in ledger, name
   has no body match, OR the name matches multiple blocks (ambiguous,
   refusing to remove — pass `--feat-id` instead).

2. **Stage + commit + push** — three paths
   (`feature_expansion/.../body.md`, the state JSON, the ledger):

   ```
   feature_expansion(remove): <name>
   ```

3. **Echo the propagation hint** — downstream tiers that referenced
   the dropped feat go stale. Don't auto-open the propagation:

   ```
   next: /propagate_downstream from feature_expansion:$comp_id — dropped feat may have orphaned downstream resps
   ```

## Don't

- Don't pass both `--feat-id` and `--name`; the CLI rejects that.
- Don't pass neither; the CLI rejects that too.
- Don't try to "clean up" the requirements body to remove dangling
  `<feat id="...">` refs as part of this commit — that's the
  /modify_requirements skill's job.
- Don't auto-propagate.

## Output

One line: which feature was removed, the commit sha, and the
propagation hint.
