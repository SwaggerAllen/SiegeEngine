---
name: continue
description: Resume an interrupted batch operation by walking its scope_keys and processing any that are still incomplete. Reads `state/batches/<id>.json` to find gaps and fires the relevant per-scope skills to fill them. Mirrors the "resume by gap-fill" pattern from the old backend's POST /batches/:id/resume.
---

# /continue <batch_id>

Resume an interrupted batch. The principle is "fill the gaps, don't
re-do completed work" — a batch with 10 scopes where 7 are
already drafted only re-fires the remaining 3.

## Inputs

- `batch_id` — the id from `state/batches/<id>.json`
- `ref` — git ref

## Steps

1. **Read the batch.** Run `python3 -m siege.cli list-batches`
   and find the one with the matching id. If status is already
   `complete`, this is a no-op — surface and stop.
2. **Walk scope_keys.** For each scope, run `python3 -m siege.cli get-state
   --tier <tier> <scope flags>` (`--comp-id "$comp_id"` for
   feature_expansion / requirements / sysarch / comparch / fanin;
   `--parent-id "$parent_id" --sub-id "$sub_id"` for subcomparch / impl;
   add `${phase:+--phase "$phase"}` for phased impl / fanin scopes)
   and compare actual state to the batch's intended end-state:
   - `op_type=regen_below_threshold` → end state is `drafted` (with a
     fresh review on top). If `status == drafted` AND the draft is
     newer than the batch's started_at, skip. Otherwise, re-fire the
     appropriate `regen-*-with-feedback` skill.
   - `op_type=reset_all` → end state is `absent`. Re-fire `mark-drafted`
     into absent, or run the `repair-state-drift`-shaped reset.

   **Phased impl/fanin scopes carry `phase`.** A scope_key for a
   phased impl/fanin node includes a `phase` field — pass it through
   to `get-state` *and* to the re-fired skill. Dropping it makes
   `get-state` query the phase-less scope, which is always `absent`,
   so the gap never closes and `/continue` re-fires that node forever.
   If a batch's impl/fanin scope_keys lack `phase` entirely, the batch
   predates phasing — treat those scopes as unphased (legacy).
3. **Update batch status.** Mark `partial` while in progress, `complete`
   when all gaps filled, `failed` if 3 consecutive scopes fail.
4. **Report.**

## Output

```
batch=<id> op=<op_type> tier=<tier>
gaps before: N
gaps after: N
status: complete | partial | failed
```
