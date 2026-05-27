---
name: remove-responsibility
description: Delete a responsibility from the requirements substrate body. Mechanical, no LLM — wraps `siege remove-responsibility`. Use when the user says "drop resp X" or "/remove_resp X". Identifies the target by either `resp_id` (resolved through the ledger) or `name`.
---

# Remove a responsibility

The mechanical inverse of `add-responsibility`. Deletes one
`<responsibility>` block from the requirements body, drops it from
the ledger, and flips state back to `drafted`. Downstream tiers that
reference the dropped resp (sysarch components claiming it, comparch
`<owns>` blocks, plan impls' `closure_resp_ids`) go stale; the skill
does not propagate.

## Inputs

- Exactly one of:
  - `resp_id` — stable `resp_*` id, resolved through
    `ids/requirements/$comp_id.json`
  - `name` — the body's `<name>` text, matched case-insensitively
- (optional) `comp_id` — substrate-root scope (default: `proj`)

## Steps

1. **Run the CLI subcommand:**

   ```bash
   ARGS=()
   [ -n "${resp_id:-}" ] && ARGS+=(--resp-id "$resp_id")
   [ -n "${name:-}" ]    && ARGS+=(--name "$name")
   python3 -m siege.cli remove-responsibility "${ARGS[@]}"
   ```

   Non-zero exits: id not in ledger, name has no body match, OR name
   matches multiple blocks (refusing to remove — pass `--resp-id`
   instead).

2. **Stage + commit + push** — three paths:

   ```
   requirements(remove): <name>
   ```

3. **Echo the propagation hint** — note that the dropped resp may
   leave dangling refs in sysarch / comparch / plan:

   ```
   next: /propagate_downstream from requirements:$comp_id — sysarch / comparch / plan may carry stale refs to the dropped resp
   ```

## Don't

- Don't try to "fix up" sysarch's `<responsibilities>` assignment or
  the plan's `closure_resp_ids` as part of this commit. Those are
  propagation work, not authoring work.
- Don't auto-propagate.

## Output

One line: which resp was removed, the commit sha, the propagation
hint.
