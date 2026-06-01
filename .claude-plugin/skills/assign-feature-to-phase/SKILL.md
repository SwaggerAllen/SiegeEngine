---
name: assign-feature-to-phase
description: Assign a feature to a phase (and strip it from any other phase first — a feature lives in at most one phase). Mechanical, no LLM — wraps `siege assign-feature-to-phase`. Use when the user says "move feat X to phase Y" or "/assign_feature_to_phase feat_X phase_Y".
---

# Assign a feature to a release phase

A feature lives in **at most one** phase — the CLI strips it from any
prior phase before adding it to the target. That keeps the
feature→phase map a clean function and prevents the same feature from
being scheduled across two phases.

## Inputs

- `feat_id` — the feature's stable `feat_*` id (look up via
  `ids/feature_expansion/proj.json` if you only have the name)
- `phase_id` — the target phase

## Steps

1. **Run the CLI subcommand:**

   ```bash
   python3 -m siege.cli assign-feature-to-phase \
     --feat-id "$feat_id" \
     --phase-id "$phase_id"
   ```

   Stdout reports `moved_from` (the prior phase the feat was in, or
   `null` if this is its first assignment) and the target phase. The
   `action` field is `"noop"` if the feat was already in the target
   phase.

2. **Stage + commit + push** — typically two phase JSON files change
   (the source phase loses the feat_id, the target gains it):

   ```
   plan(assign): <feat_id> -> <phase_id>
   ```

3. **Echo the follow-up sequence** — only the final mint matters for
   the impl tree:

   ```
   next: when done batching, `siege mint-plan --dry-run` previews the impl-tree change, then `siege mint-plan` materializes
   ```

## Don't

- Don't auto-run mint-plan. The user typically batches several
  assignments.
- Don't auto-propagate.

## Output

One line: feat moved from-where to-where, the commit sha, the
follow-up hint.
