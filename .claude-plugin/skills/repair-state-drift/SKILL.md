---
name: repair-state-drift
description: Recompute body_sha256 for a scope's state JSON when the MCP server reports drift. Use when `get_state` returns a `drift` block on a scope you trust the body of — this skill writes a new state JSON with the correct sha and bumps nonce.
---

# Repair state JSON drift

Drift means the state JSON's recorded `body_sha256` doesn't match the
actual sha256 of the body file's bytes on the ref. This usually means
a body was edited without re-running the draft skill (or a merge
created a divergent body without a state update). The repair is to
recompute the sha and write a new state JSON.

## Inputs

- `ref`, `tier`, `comp_id` (or `parent_id` + `sub_id`)
- (optional) `expected_status` — if set, the skill will refuse to
  repair if the state's status doesn't match. Defaults to no check.

## Steps

1. Read the body file at `draft.body_path` and `review.body_path` (if
   the review block is present).
2. Recompute sha256 for each.
3. Read the existing state JSON.
4. Update the `body_sha256` fields where they're stale. Don't touch
   any other field except `nonce` (mint fresh).
5. Commit one commit:
   `repair(<tier>/$id): recompute body_sha256 (drift)`
6. Push.

## Don't

- Don't repair drift on an `approved` scope without explicit user
  confirmation — drift on an approved artifact usually means
  something more serious is wrong (a merge that mangled content)
  and silently recomputing the sha papers over it.

## Output

What changed (old sha → new sha for each file) + commit sha.
