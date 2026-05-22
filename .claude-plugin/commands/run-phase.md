---
name: run_phase
description: Build one phase's impl slice. Reads state/plan.json, recomputes the plan live and refuses on divergence or hard errors, then drafts + reviews every impl node in the phase's topological build order followed by the phase's fan-in. The phased counterpart of /run_tier for the impl + fanin tiers.
---

# /run_phase <n>

Build the impl + fan-in slice for phase `order = <n>`. The phase
registry (`state/phases/`) assigns features to ordered phases; a leaf
subcomponent gets one impl node per phase it picks up work in, and
fan-in recomputes per phase. This command executes exactly one
phase's worth of that work.

Run `/mint_plan` first — it materializes `state/plan.json` and the
per-node `absent` impl state files this command drafts into.

## Inputs

- `n` — the phase `order` (integer) to build
- `ref` — git ref (default: current branch)
- (optional) `auto_approve` — if true, approve each reviewed node.
  Default: false.

## Steps

1. **Recompute the plan live.** Run `python3 -m siege.cli compute-plan`.
   - If `errors` is non-empty, STOP — surface every error. A hard
     error (unassigned feature, closure-changed-after-draft) means
     the phase is not safe to build.
2. **Load `state/plan.json` from disk.** If it is missing, STOP and
   tell the user to run `/mint_plan` first.
3. **Divergence guard.** Compare the on-disk `plan.json` to the live
   `compute-plan` result for phase `<n>` — specifically its
   `impl_nodes` (parent/sub/phase + `closure_resp_ids`) and
   `build_order`. If they differ, the registry / comparch /
   subcomparch changed since `mint-plan` last ran. STOP and tell the
   user to re-run `/mint_plan`, then retry — the on-disk `absent`
   impl nodes carry a stale responsibility closure and drafting off
   them would bake in the wrong slice.
4. **Locate the phase.** Find the phase with `order == n`. If there is
   none, STOP — surface the available phase orders.
5. **Mint a batch.** Write `state/batches/batch_<id>.json` with
   `op_type="run_phase"`, `tier="impl"`, `status="pending"`, and a
   `scopes` list of every impl node in the phase. **Each scope entry
   MUST carry `phase`** (`{"tier":"impl","parent_id":...,"sub_id":...,"phase":n}`)
   — `/continue` resumes off these keys and a phase-less impl key
   never resolves.
6. **Build the impl nodes** in the phase's `build_order` (already
   topologically sorted — a dependency comp's nodes precede its
   dependents'). For each `{parent_id, sub_id, phase}`:
   a. Confirm the `absent` state file exists at
      `state/impl/<parent_id>/p<n>/<sub_id>.json`. If it does not,
      `mint-plan` did not run for this node — STOP and surface it.
   b. Call `draft-impl` with `parent_id`, `sub_id`, `phase=n`,
      `batch_id`. Skip if the node is already `drafted`/`reviewed`/`approved`.
   c. Call `review-impl` with the same `parent_id`, `sub_id`, `phase=n`.
      Skip if already `reviewed`.
   d. If `auto_approve`, call `mark-approved` (tier `impl`, with `phase=n`).
7. **Build the phase's fan-in.** For each distinct comp (`parent_id`)
   that has an impl node in this phase, in `build_order` comp order:
   a. Call `draft-fanin` with `comp_id=<parent_id>`, `phase=n`,
      `batch_id`. Fan-in@n reads every impl at phase ≤ n (deduped per
      sub) — so a comp whose subs were last touched in an earlier
      phase still gets a phase-n fan-in that reflects the cumulative
      build.
   b. Call `review-fanin` with the same `comp_id`, `phase=n`.
   c. If `auto_approve`, call `mark-approved` (tier `fanin`, `phase=n`).
8. **Stop on first persistent failure.** If a node fails validate 3
   times running, surface the error and stop. Update the batch to
   `partial`. The user fixes the prompt / context and re-runs
   `/run_phase <n>` (or `/continue <batch_id>`) — completed nodes are
   skipped.
9. **Finalize the batch** — `complete` if every node landed, `partial`
   otherwise.

## Fan-out (optional)

When the phase has > 1 ready impl node at the same `build_order`
layer (no dependency edge between them), the orchestrator MAY fan out
to `agents/generator-impl` for parallel drafting — pass each scope
dict with its `phase`. Fan-in serializes after all of the phase's
impl nodes commit.

## Don't

- Don't build a phase when `compute-plan` reports `errors`.
- Don't build off a stale `plan.json` — re-run `/mint_plan` on
  divergence.
- Don't push to a branch other than `$ref`. Don't create a PR.
- Don't mutate the phase registry (`state/phases/`).

## Output

```
phase: order=<n> name=<name>
impl nodes: N drafted (+ M existing), N reviewed, N approved
fan-in: N drafted, N reviewed, N approved
failed: N — <one-line per failure>
score histogram: 0-30:N | 31-60:N | 61-85:N | 86-100:N
batch_id: <id>
next: /run_phase <n+1>  (or "all phases built" if this was the last)
```
