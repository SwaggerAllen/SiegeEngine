---
name: remove-phase
description: Delete a phase from the registry. Mechanical, no LLM — wraps `siege remove-phase`. Use when the user says "drop phase X" or "/remove_phase X". Refuses to remove a phase that still owns features (the user has to unassign them first).
---

# Remove a release phase

Deletes `state/phases/<phase_id>.json`. Refuses if the phase still
owns feature ids — the user must unassign them first (typically by
moving them to a different phase via `/assign_feature_to_phase`).

## Inputs

- `phase_id` — the phase to drop

## Steps

1. **Run the CLI subcommand:**

   ```bash
   python3 -m siege.cli remove-phase --phase-id "$phase_id"
   ```

   Non-zero exit: phase file missing, OR phase's `feature_ids` is
   non-empty. The error message lists the still-attached feat_ids
   so the user knows what to move.

2. **Stage + commit + push:**

   ```
   plan(remove-phase): <phase_id>
   ```

3. **Echo the follow-up sequence:**

   ```
   next: `siege mint-plan --dry-run` to preview the impl-tree impact; if existing impls were planned for this phase, `siege open-propagation --from-plan-change` will surface them as dropped-by-plan
   ```

## Don't

- Don't auto-unassign features from a phase that's about to be
  removed — feature reassignment is the user's deliberate call, not
  a side effect.
- Don't auto-propagate.

## Output

One line: which phase was removed, the commit sha, the follow-up
hint.
