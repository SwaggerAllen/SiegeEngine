---
name: mint-plan
description: Materialize the impl-tier phasing plan. Calls `compute_plan`, writes `state/plan.json`, and mints one `absent`-status impl state JSON per planned node (phase-scoped, with the responsibility closure pre-seeded). Idempotent and additive — never touches a node already drafted+. Triggers on "mint plan", "/mint_plan", or before the first `/run_phase`.
---

# Mint the phasing plan

`compute_plan` is a pure projection — it *describes* the per-phase
impl nodes but writes nothing. This skill is the writer: it runs
`compute_plan`, persists the plan, and pre-creates the impl state
files so `/run_phase` has something concrete to draft into.

Run this once after the phase registry (`state/phases/<id>.json`) is
written, and again any time the registry, comparch, or subcomparch
tiers change.

## Inputs

- `ref` — git ref to read from and commit on (default: current branch)

## Steps

1. **Compute the plan.** Call `mcp__siegeengine__compute_plan(ref=$ref)`.
2. **Refuse on hard errors.** If the result's `errors` list is
   non-empty, STOP. Surface every error verbatim and do not write
   anything. Hard errors (an unassigned feature, a closure that
   changed under an already-drafted node) mean the plan is not safe
   to materialize — the user fixes the registry or regenerates the
   stale node, then re-runs `mint-plan`.
3. **Write `state/plan.json`.** Serialize the `compute_plan` result
   verbatim (it already has `schema_version`, `ref`, `computed_at`,
   `phases`, `rearrangements`, `errors`, `warnings`, `aggregates`).
4. **Surface rearrangements.** If `rearrangements` is non-empty, print
   each `line` — these are components a dependency pulled earlier than
   their assigned phase. The registry was NOT mutated; this is the
   report the user asked for. Not an error, just visibility.
5. **Mint the impl nodes.** Run the inline `python3` below. For each
   planned impl node it writes an `absent`-status impl state JSON at
   the phased path with `meta.parent_resps` pre-seeded to the node's
   cumulative `closure_resp_ids`. It is **idempotent and additive**:
   a node already at `drafted` / `reviewed` / `approved` is left
   untouched; an `absent` node is re-seeded (the closure may have
   grown). It also reports — but never deletes — phased impl nodes on
   disk that the new plan no longer includes.

   ```bash
   python3 - <<'PY'
import json, os, secrets, time

alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
def mint_nonce():
    b = secrets.randbits(128)
    return "".join(reversed([alphabet[(b >> (5 * i)) & 0x1F] for i in range(26)]))

plan = json.loads(open("state/plan.json").read())
minted, reseeded, skipped = [], [], []
planned = set()
for phase in plan.get("phases", []):
    for node in phase.get("impl_nodes", []):
        parent, sub, n = node["parent_id"], node["sub_id"], node["phase"]
        state_path = f"state/impl/{parent}/p{n}/{sub}.json"
        planned.add(state_path)
        prior = {}
        if os.path.exists(state_path):
            prior = json.loads(open(state_path).read())
            if prior.get("status") in ("drafted", "reviewed", "approved"):
                skipped.append(state_path)
                continue
        meta = dict(prior.get("meta", {}))
        meta["parent_resps"] = node["closure_resp_ids"]
        state = {
            "schema_version": 2,
            "scope": {"tier": "impl", "comp_id": None,
                      "parent_id": parent, "sub_id": sub, "phase": n},
            "status": "absent",
            "nonce": mint_nonce(),
            "is_foundation": prior.get("is_foundation", False),
            "edges": prior.get("edges", {}),
            "meta": meta,
        }
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        open(state_path, "w").write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        (reseeded if prior else minted).append(state_path)

# Surface (do not delete) phased impl nodes the new plan dropped.
dropped = []
for root, _, files in os.walk("state/impl"):
    seg = os.path.basename(root)
    if not (seg.startswith("p") and seg[1:].isdigit()):
        continue
    for f in files:
        if f.endswith(".json"):
            p = os.path.join(root, f)
            if p not in planned:
                dropped.append(p)

print(json.dumps({"minted": minted, "reseeded": reseeded,
                   "skipped_built": skipped, "dropped_by_plan": dropped},
                  indent=2))
PY
   ```

6. **Stage + commit + push.** One commit with `state/plan.json` and
   every minted/re-seeded impl state JSON:
   `mint-plan: <N> impl nodes across <M> phases`
   Push with `git push -u origin $ref` (retry on network failure up
   to 4 times with 2s / 4s / 8s / 16s backoff).

## Don't

- Don't materialize anything when `compute_plan` reports `errors`.
- Don't overwrite a `drafted` / `reviewed` / `approved` impl node —
  re-planning is additive, never destructive.
- Don't delete the `dropped_by_plan` nodes. Surface them so the user
  decides — a dropped node usually means a registry edit removed a
  feature; the user may want to keep the built artifact or clean it
  up deliberately.
- Don't touch the phase registry (`state/phases/`). It is the user's
  intent; the planner only reads it.
- Don't create a PR.

## Output

A summary:

```
plan: <M> phases, <N> impl nodes
minted: N new absent nodes
reseeded: N existing absent nodes (closure refreshed)
skipped: N already-built nodes (left untouched)
rearrangements: N — <one line each>
dropped-by-plan: N — <path each, surfaced for review>
commit: <sha>
```
