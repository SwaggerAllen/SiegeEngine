---
name: scaffold
description: Bootstrap the upstream tier chain on a fresh project. Walks features → requirements → sysarch in order, drafting + reviewing + (optionally) approving each scope. The downstream tiers (comparch onward) are out of scope for this command; use `/run_tier` after scaffolding to continue.
---

# /scaffold

Bootstrap a project's upstream chain.

## Inputs

- `ref` — git ref (default: current branch)
- `input_doc` — path to the project's input document (default:
  discovery, see below)
- (optional) `auto_approve` — if true, mark each scope `approved`
  after review. Default: false (user reviews each tier's scopes
  manually between phases).

The input doc is the only source extraction tiers read from. It's
project-specific prose (problem statement, target users, system
qualities, primary workflows). One or two pages of focused prose
beats ten pages of category-speak — extraction tiers compress hard,
so vague input produces vague handles all the way down.

### How to supply the input doc

In order of precedence:

1. **Explicit `input_doc` argument**: `/scaffold input_doc=docs/my-spec.md`.
   Use this when the file is in the project repo but not in
   `seed-docs/`.
2. **Attached file**: `/scaffold @docs/my-spec.md` — CC attaches the
   file content to the prompt directly.
3. **Pasted prose**: paste the input text into chat alongside
   `/scaffold`. Useful for one-shot scaffolds where you don't want
   to commit the input to the repo.
4. **`seed-docs/` discovery**: with no explicit input, look for
   `seed-docs/*.md` in the project repo. If exactly one file is
   present, use it; if multiple, ask the user to pick.

If none of those produce content, stop and ask. Don't proceed with a
guess — the input doc shapes everything downstream.

## Steps

1. **Resolve the input doc** per the precedence rules above.
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
   any scopes that hit validation errors and were skipped. Once
   sysarch is drafted its identity ledger (`ids/sysarch/`) names every
   top-level component — report the count and point the user at
   `/run_tier comparch` to fan out into the component tier.

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
components declared: N — next: /run_tier comparch
```
