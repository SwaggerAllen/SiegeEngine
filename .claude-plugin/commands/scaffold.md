---
name: scaffold
description: Bootstrap the upstream tier chain on a fresh project. Walks features → requirements → sysarch in order, drafting + reviewing + (optionally) approving each scope. The downstream tiers (comparch onward) are out of scope for this command; use `/run_tier` after scaffolding to continue.
---

# /scaffold

Bootstrap a project's upstream chain.

## Inputs

- `ref` — git ref (default: current branch)
- (optional) `auto_approve` — if true, mark each scope `approved`
  after review. Default: false (user reviews each tier's scopes
  manually between phases).

## Steps

1. **Confirm the input doc.** Check `seed-docs/` for the project's
   input document. If missing, ask the user where to find it.
2. **Run feature_expansion tier:**
   a. Enumerate features from the input doc.
   b. For each feature, call `draft-feature-expansion`.
   c. For each draft, call `review-feature-expansion`.
   d. Pause for user inspection (unless `auto_approve`).
   e. For each approved, call `mark-approved`.
3. **Run requirements tier:**
   a. For each approved feature, enumerate its requirements.
   b. Draft + review + (optionally) approve each requirement.
4. **Run sysarch tier:**
   a. Compose the 4 project-wide sysarch sections (project_techspec,
      project_policies, project_dependencies, project_domain_parents).
   b. Draft + review + (optionally) approve each.
5. **Report.** Summarize what was drafted, reviewed, approved. Surface
   any scopes that hit validation errors and were skipped.

## Concurrency

Within a tier, the per-scope work CAN parallelize via fan-out to
per-tier generator subagents (`agents/generator-feature-expansion`
etc.). The orchestrator computes the per-layer scope set and
dispatches one subagent per scope.

## Output

A punch list:
```
features: N drafted, N reviewed, N approved
requirements: N drafted, N reviewed, N approved
sysarch: 4 drafted, 4 reviewed, 4 approved
```
