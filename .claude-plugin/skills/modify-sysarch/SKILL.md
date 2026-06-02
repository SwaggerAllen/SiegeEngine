---
name: modify-sysarch
description: Surgically modify the existing sysarch body in response to targeted feedback. Mirrors `regen-sysarch-with-feedback`'s wrapper but uses a "preserve, don't redraft" prompt — every component, dep, and policy the feedback doesn't touch round-trips identically. Use when the user says "modify sysarch X", "tweak sysarch Y", or "/modify_sysarch <feedback>".
thinking_effort: max
---

# Modify the sysarch body

This is `draft-sysarch` with two changes: the prompt comes from
`siege/prompts/modify_sysarch.md` (the surgical-edit prompt, not the
from-scratch one), and the feedback the user just gave you is the
driving input alongside the current body. Preserve-don't-redesign is
the load-bearing discipline — see the modify prompt's preamble for the
do/don't framing.

## Inputs

- `ref` — git ref (default: current branch)
- (optional) `comp_id` — substrate-root scope (default: `proj`)
- The user's feedback (in your conversation with them) — what they
  want changed and what should stay the same.

## Steps

1. **Fetch the modify-variant context bundle.** From the repo root:

   ```bash
   python3 -m siege.cli get-context \
     --tier sysarch \
     --comp-id "$comp_id" \
     --prompt-variant modify
   ```

   This emits the same standard sysarch context (approved features,
   approved responsibilities, prior review text) plus the **current**
   body — and crucially, the `instructions` field holds the
   surgical-modify prompt instead of the from-scratch prompt. The
   bundle also carries `"prompt_variant": "modify"` so you can sanity-
   check the variant landed.

2. **Compose the modified body.** Read the bundle's `instructions` —
   the preserve-don't-redesign rules + the per-feedback-type
   templates ("rename X to Y", "split X into A+B", "address review
   finding #N", etc.). Thread the user's feedback through those
   rules. Emit the full body verbatim with **only** the edits the
   feedback asks for. This is a top-of-chain tier — use the deepest
   thinking budget.

3. **Write the body file** to `sysarch/$comp_id/body.md`.

4. **Materialize state JSON + identity ledger** via:

   ```bash
   python3 -m siege.cli write-draft \
     --tier sysarch \
     --comp-id "$comp_id" \
     --body-path "sysarch/$comp_id/body.md" \
     --thinking-effort max
   ```

   The CLI validates the body (alias rules, foundation marker,
   acyclicity, domain-parent cap, resp coverage); a non-zero exit
   means the validator caught a structural error — surface stderr,
   re-compose (step 2), retry up to 3 times. Component-level aliases
   carry forward from the prior ledger by alias, so the identity of
   every untouched component stays stable.

5. **Stage + commit + push.** One commit, three paths
   (`sysarch/$comp_id/body.md`, the state JSON, the ledger):

   ```
   modify(sysarch/$comp_id): <one-line summary of the edit>
   ```

6. **Echo the propagation hint:**

   ```
   next: /propagate_downstream from sysarch:$comp_id when ready
   ```

## Don't

- Don't redraft components the feedback didn't ask you to touch.
  Their handles are grounded in downstream prompts; rewriting them
  creates drift the user didn't ask for.
- Don't rename aliases unless the user explicitly asked. Aliases are
  identity keys — a renamed alias orphans every comparch / subcomparch
  / impl underneath it.
- Don't auto-propagate.

## Output

One line: what changed, the commit sha, the propagation hint.
