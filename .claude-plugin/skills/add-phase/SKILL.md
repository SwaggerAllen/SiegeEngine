---
name: add-phase
description: Add a new phase to the project's phase registry (`state/phases/<phase_id>.json`). Mechanical, no LLM — wraps `siege add-phase`. Use when the user says "add phase X", "/add_phase X", or is laying out the release plan. Mints a fresh `phase_id`; refuses duplicate `--order`.
---

# Add a release phase

The phase registry assigns features to ordered release phases — input
to `compute-plan`, which projects per-phase impl nodes. Phase changes
don't auto-propagate; the user runs `mint-plan` (optionally
`--dry-run` first) and `open-propagation --from-plan-change` after
they batch their edits.

## Inputs

- `name` — display name, e.g. `"Phase 1 — MVP"`
- `order` — phase ordinal (1, 2, 3, …). Must be unique across the
  registry; the CLI rejects collisions.
- (optional) `phase_id` — override the minted id (rare; use for
  testing or reproducible builds)

## Steps

1. **Run the CLI subcommand:**

   ```bash
   ARGS=(--name "$name" --order "$order")
   [ -n "${phase_id:-}" ] && ARGS+=(--phase-id "$phase_id")
   python3 -m siege.cli add-phase "${ARGS[@]}"
   ```

   It writes `state/phases/<phase_id>.json` with
   `{schema_version: 2, phase_id, order, name, feature_ids: []}`.
   Non-zero exit: duplicate `phase_id` or duplicate `order`.

2. **Stage + commit + push:**

   ```
   plan(add-phase): <name> @ order=<N>
   ```

3. **Echo the follow-up sequence** — phase additions don't change
   the live plan until `mint-plan` runs:

   ```
   next: assign features via /assign_feature_to_phase, then preview with `siege mint-plan --dry-run`, then materialize with `siege mint-plan`, then if existing impls need regen: `siege open-propagation --from-plan-change`
   ```

## Don't

- Don't auto-run mint-plan. The user typically wants to add multiple
  phases + assign features before re-minting.
- Don't auto-propagate.

## Output

One line: the minted `phase_id`, the commit sha, the follow-up hint.
