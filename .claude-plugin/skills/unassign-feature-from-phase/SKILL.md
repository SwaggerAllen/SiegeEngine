---
name: unassign-feature-from-phase
description: Remove a feature from a phase's `feature_ids` list. Mechanical, no LLM — wraps `siege unassign-feature-from-phase`. Use when the user wants to take a feature out of the release plan without moving it to another phase. Errors if the feature wasn't assigned.
---

# Unassign a feature from a phase

Drops a feat_id from one phase's `feature_ids`. Doesn't move it
anywhere — the feature ends up unassigned, which the plan projection
will then flag as `errors: ["feature <id> is not assigned to any
phase"]` until the user either re-assigns it or drops the feature
itself via `/remove_feature`.

## Inputs

- `feat_id` — the feature to unassign
- `phase_id` — the phase to remove it from

## Steps

1. **Run the CLI subcommand:**

   ```bash
   python3 -m siege.cli unassign-feature-from-phase \
     --feat-id "$feat_id" \
     --phase-id "$phase_id"
   ```

   Non-zero exit: feat wasn't in this phase's `feature_ids`.

2. **Stage + commit + push:**

   ```
   plan(unassign): <feat_id> from <phase_id>
   ```

3. **Echo the follow-up sequence:**

   ```
   next: `siege compute-plan` will now report this feat as unassigned. Either /assign_feature_to_phase to another phase, or /remove_feature to drop it entirely
   ```

## Don't

- Don't try to "move" the feat to a different phase as a single
  operation — use `/assign_feature_to_phase` instead, which handles
  the move atomically.
- Don't auto-propagate.

## Output

One line: feat unassigned from where, the commit sha, the follow-up
hint.
