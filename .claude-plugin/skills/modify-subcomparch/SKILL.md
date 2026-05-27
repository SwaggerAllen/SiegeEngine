---
name: modify-subcomparch
description: Surgically modify an existing subcomparch body in response to targeted feedback. Same wrapper as `regen-subcomparch-with-feedback` but the prompt is the "preserve, don't redraft" variant — each of the six sections (techspec, pubapi, privapi, internal_structure, policies, failure_surface) is independently sticky. Use when the user says "modify subcomparch" or "/modify_subcomparch <parent_id> <sub_id> <feedback>".
---

# Modify a subcomparch body

This is `draft-subcomparch` with the modify prompt variant. The six
sections of the body are independently sticky — touch only the
section(s) the feedback names, leave the others verbatim. See
`siege/prompts/modify_subcomparch.md` for the per-section discipline.

## Inputs

- `ref` — git ref (default: current branch)
- `parent_id` — top-level comp this sub belongs to
- `sub_id` — the sub's stable id
- The user's feedback (in your conversation with them)

## Steps

1. **Fetch the modify-variant context bundle:**

   ```bash
   python3 -m siege.cli get-context \
     --tier subcomparch \
     --parent-id "$parent_id" \
     --sub-id "$sub_id" \
     --prompt-variant modify
   ```

   The bundle carries the standard subcomparch context (this sub's
   `<owns>` claims from the parent comparch, related-features
   summary scoped to those claims, parent comparch's non-subcomponent
   fragments — techspec / pubapi / privapi / policies /
   failure_surface — sibling sub pubapis, project sysarch sections,
   prior review text) plus the current body. The `instructions` field
   carries the modify prompt.

2. **Compose the modified body.** Identify which section(s) the
   feedback touches — pubapi, privapi, internal_structure,
   failure_surface, policies, or techspec. Edit only those. Preserve
   every untouched section verbatim. Subcomparch's `thinking_effort`
   is unset by design (handles already compressed upstream); just
   compose.

3. **Write the body file** to
   `subcomparch/$parent_id/subs/$sub_id/body.md`.

4. **Materialize state JSON** via:

   ```bash
   python3 -m siege.cli write-draft \
     --tier subcomparch \
     --parent-id "$parent_id" \
     --sub-id "$sub_id" \
     --body-path "subcomparch/$parent_id/subs/$sub_id/body.md"
   ```

   Subcomparch doesn't derive an identity ledger (it has no sub-nodes
   the next tier reads); the validator runs the same checks as the
   regen path.

5. **Stage + commit + push** with message:
   `modify(subcomparch/$parent_id/$sub_id): <one-line summary>`

6. **Echo the propagation hint:**

   ```
   next: /propagate_downstream from subcomparch:$parent_id/$sub_id when ready
   ```

## Don't

- Don't re-articulate pubapi on a privapi-focused edit. Pubapi
  changes propagate to every dependent sub's privapi.
- Don't add "while we're here" failure modes or policies. Each entry
  is a coverage commitment in impl.
- Don't auto-propagate.

## Output

One line: which section(s) changed, the commit sha, the propagation
hint.
