---
name: propose-feature
description: Propose a new feature from a one-line user description. Runs the LLM to canonicalize a name + intent paragraph, then mechanically appends it via `siege add-feature`. Use when the user says "propose a feature for X", "design a feature that does X", "I want a feature that...", or `/propose_feature X` — i.e. when they have a rough sketch and want it named and intent-written, not a hand-supplied name+intent pair (that's `/add_feature`).
thinking_effort: max
---

# Propose a feature

This is the **chat-driven authoring** entry point for the feature_expansion
tier — the user has a sketch in mind, you turn it into a canonical
`<feature>` block (name + intent paragraph, plus an optional `<implicit/>`
marker), then hand the canonical pair off to the existing mechanical
add-feature primitive.

Use this when the user describes what they want with a one-liner. Use
`/add_feature` instead when the user supplies the exact name and intent
themselves.

## Inputs

- `description` — the user's one-line sketch of the feature, e.g.
  `"users export reports to CSV"`. Required.
- (optional) `name_hint` — the user's preferred name. The LLM may
  polish to match the project's naming convention but treats it as a
  strong preference.
- (optional) `comp_id` — substrate-root scope (default: `proj`)
- (optional) `implicit` — set `true` only when the user explicitly
  marks the feature as scaffolding the project obviously needs but
  the input doc doesn't call out. Otherwise leave unset and let the
  LLM decide from the description + input doc.

## Steps

1. **Fetch generation context.** From the repo root:

   ```bash
   python3 -m siege.cli get-context --tier feature_expansion --comp-id "$comp_id"
   ```

   The bundle carries the prompt instructions, the project's
   `input_docs` (every `inputs/<role>.md` in the repo), and the
   existing `sibling_features` list with name + summary per feature.
   The CLI projects the committed tree at `HEAD` — no server.

2. **Compose the feature.** Use the bundle's `instructions` text
   (which is `siege/prompts/propose_feature.md`), the `input_docs`,
   the `sibling_features` summary, the user's `description`, and the
   optional `name_hint`. Output: exactly one `<feature>` block with
   `<name>` + `<intent>` (+ optional `<implicit/>`). This is a
   top-of-chain tier — use the deepest thinking budget you can.

3. **Extract the canonical name and intent.** Use `awk` to pull the
   tag bodies out of the single-feature output (the prompt enforces
   exactly one `<feature>` block, so a regex-based extractor is
   safe):

   ```bash
   name=$(awk 'BEGIN{RS="<name>"} NR==2{sub(/<\/name>.*/,""); print}' draft.xml)
   intent=$(awk 'BEGIN{RS="<intent>"} NR==2{sub(/<\/intent>.*/,""); print}' draft.xml)
   grep -q "<implicit/>" draft.xml && implicit=true || implicit=
   ```

   If `name` or `intent` is empty, abort — the LLM violated the
   single-block contract. Surface the raw output to the user.

4. **Run the mechanical add.** From the repo root:

   ```bash
   ARGS=(--name "$name" --intent "$intent")
   [ "${implicit:-}" = "true" ] && ARGS+=(--implicit)
   [ -n "${comp_id:-}" ] && ARGS+=(--comp-id "$comp_id")
   python3 -m siege.cli add-feature "${ARGS[@]}"
   ```

   This appends the `<feature>` block to
   `feature_expansion/$comp_id/body.md`, re-derives the slim identity
   ledger (minting a fresh `feat_*` id), and flips the state JSON
   back to `drafted`. Stdout is a JSON line with `feat_id` +
   `body_path` + `state_path` + `ids_path`.

   A non-zero exit usually means a duplicate name slipped through
   the LLM's uniqueness check. Surface the error; if appropriate,
   ask the user whether to retry with a sharper name and rerun
   step 2 with the duplicate flagged in the description.

5. **Stage + commit + push.** One commit, three paths:
   `feature_expansion/$comp_id/body.md`,
   `state/feature_expansion/$comp_id.json`, and
   `ids/feature_expansion/$comp_id.json`:

   ```
   feature_expansion(propose): <name>
   ```

   Push with `git push -u origin <branch>` (retry on network failure
   up to 4 times with 2s / 4s / 8s / 16s backoff).

6. **Echo the propagation hint.** Don't auto-propagate — the user
   batches their adds and triggers propagation once:

   ```
   next: /propagate_downstream from feature_expansion:$comp_id when ready
   ```

## Don't

- Don't redraft the whole feature_expansion body — that's
  `/draft_feature_expansion` or `/regen_feature_expansion_with_feedback`.
- Don't auto-propagate. Manual propagation is the design.
- Don't push to a branch other than the session's working branch.
- Don't add vocabulary entries in the same flow — vocab goes through
  `/create_vocab` separately.
- Don't propose more than one feature per invocation. If the user's
  description fans into multiple workflows, propose the load-bearing
  one and surface the others in your reply so the user can call
  `/propose_feature` again for each.

## Output

One line summarizing the proposed feature's name, the minted
`feat_id`, the commit sha, and the propagation hint.
