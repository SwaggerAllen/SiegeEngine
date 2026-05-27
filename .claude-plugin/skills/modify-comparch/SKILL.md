---
name: modify-comparch
description: Surgically modify an existing comparch body in response to targeted feedback. Same wrapper as `regen-comparch-with-feedback` but the prompt is the "preserve, don't redraft" variant — every subcomponent, `<owns>` claim, dep, and section the feedback doesn't touch round-trips identically. Use when the user says "modify comparch X" or "/modify_comparch <comp_id> <feedback>".
thinking_effort: max
---

# Modify a comparch body

This is `draft-comparch` with the modify prompt variant. The current
body + the user's feedback together drive a tightly-scoped edit. See
`siege/prompts/modify_comparch.md` for the preserve-don't-redesign
discipline that governs what to touch and what to leave alone.

## Inputs

- `ref` — git ref (default: current branch)
- `comp_id` — the top-level comp whose comparch you're modifying
- The user's feedback (in your conversation with them)

## Steps

1. **Fetch the modify-variant context bundle:**

   ```bash
   python3 -m siege.cli get-context \
     --tier comparch \
     --comp-id "$comp_id" \
     --prompt-variant modify
   ```

   The bundle carries the standard comparch context (parent_resps,
   related features, sibling pubapi fragments, project sysarch
   sections, already-applied policies, prior review text) plus the
   current body, and `instructions` is the surgical-modify prompt.

2. **Compose the modified body.** Thread the user's feedback through
   the modify prompt's preserve-don't-redesign rules. The per-feedback-
   type templates ("rename sub X", "move resp R from A to B", "edit
   only the pubapi section", "address review finding #N") tell you
   which surfaces to touch and which to leave verbatim. Deepest
   thinking budget — comparch reads pubapis verbatim, so handle
   quality matters.

3. **Write the body file** to `comparch/$comp_id/body.md`.

4. **Materialize state JSON + identity ledger:**

   ```bash
   python3 -m siege.cli write-draft \
     --tier comparch \
     --comp-id "$comp_id" \
     --body-path "comparch/$comp_id/body.md" \
     --thinking-effort max
   ```

   The CLI validates and re-derives the slim subcomponent ledger.
   Subcomponent aliases carry forward — a renamed alias here orphans
   the subcomparch + impl underneath that sub.

5. **Stage + commit + push** with message:
   `modify(comparch/$comp_id): <one-line summary>`

6. **Echo the propagation hint:**

   ```
   next: /propagate_downstream from comparch:$comp_id when ready
   ```

## Don't

- Don't re-articulate every `<owns>` block to "tighten" them — that
  reshuffles ownership the user isn't questioning.
- Don't reword the pubapi unless the feedback asks. Pubapi changes
  propagate to every dependent comp's privapi.
- Don't auto-propagate.

## Output

One line: what changed, the commit sha, the propagation hint.
