---
name: status
description: Print a per-tier snapshot of the project — for each tier, counts of absent / drafted / reviewed / approved, score histogram, and the worst-N scopes by review score. Read-only; no commits. Use after a long batch or at the start of a session to orient.
---

# /status

Read-only project snapshot.

## Inputs

- `ref` — git ref (default: current branch)
- (optional) `worst_n` — show this many worst-scored scopes per tier
  (default: 5)

## Steps

1. For each tier in (feature_expansion, requirements, sysarch,
   comparch, subcomparch, impl, fanin):
   - Call `mcp__siegeengine__get_structure_summary` for counts.
   - Call `mcp__siegeengine__get_review_summary` for score histogram +
     worst-N scopes.
2. Render a single table per tier:

```
=== feature_expansion ===
total=N | absent=N | drafted=N | reviewed=N | approved=N
scores: 0-30:N | 31-60:N | 61-85:N | 86-100:N
worst 5:
  - feat_a (score=23): <intro first sentence>
  - feat_b (score=31): <intro first sentence>
  ...
```

3. End with a one-line gate read: "next action: <suggestion>" — e.g.
   "run /run_tier comparch" if everything upstream is approved and
   comparch has absent scopes.

## Output

Pure stdout, no commits. Suitable for piping into a journal entry.
