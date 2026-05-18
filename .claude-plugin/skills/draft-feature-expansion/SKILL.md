---
name: draft-feature-expansion
description: Draft a feature expansion artifact. Reads `get_generation_context` for the feature scope, drafts the body, validates it, then commits state + body in one commit and pushes. Triggers when the user says "draft feature <id>", "/draft_feature <id>", or after `/scaffold` enumerates pending feature scopes.
thinking_effort: max
---

# Draft a feature expansion

You are drafting the expanded form of one feature. This is the top of the
tier stack — there are no upstream tier artifacts to consult, only the
project input doc and any sibling features.

## Inputs

The user provides:

- `feat_id` — the feature's stable id
- `ref` — the git ref to read from and commit on (default: current branch)

## Steps

1. Call `mcp__siegeengine__get_generation_context(ref=$ref, tier="feature_expansion", scope={"tier": "feature_expansion", "comp_id": $feat_id})`.
2. Compose a draft using the instructions and context from the bundle.
   Use the maximum thinking budget — this is the most upstream tier and
   downstream tiers cannot recover from a sloppy expansion.
3. Call `mcp__siegeengine__validate_artifact(ref=$ref, tier="feature_expansion", scope=..., body=$draft)`.
4. If validation fails, fix the issues by re-running step 2 with the
   errors as feedback. Loop up to 3 times. If still failing, surface the
   errors to the user and stop.
5. Write the body to `feature_expansion/$feat_id/body.md`.
6. Update `state/feature_expansion/$feat_id.json` with status `drafted`,
   the body sha256, generated_at, generator_metadata, and a fresh nonce.
7. Stage both files, commit with message:
   `draft(feature_expansion/$feat_id): <one-line summary>`
8. Push with `git push -u origin $ref`.

## Validation gate

Don't commit a draft that fails `validate_artifact`. Loop instead.
Don't overwrite an existing draft without first reading its state — if
the existing status is `reviewed` or `approved`, abort and ask the user
to run `regen-feature-expansion-with-feedback` or to explicitly clear
the state first.

## Output

A one-line summary of what was drafted, the commit sha, and a link to
the committed body in the GitHub UI.
