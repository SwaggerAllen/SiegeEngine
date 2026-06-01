---
name: add-feature
description: Append a new feature to the feature_expansion substrate body. Mechanical, no LLM — wraps `siege add-feature`. Use when the user says "add feature X", "/add_feature X", or asks to extend the feature set without redesigning anything else. Mints a fresh `feat_*` id, flips state back to drafted, leaves propagation manual.
---

# Add a feature

This is the **authoring** entry point for the feature_expansion tier — it
extends the feature set by one item without redrafting the whole body
through an LLM. Use it when the user names a concrete feature they
want to add (with a one-sentence intent) and is not asking for a
broader redraft.

## Inputs

- `name` — the user-facing feature name, e.g. `"Saved Searches"`
- `intent` — one sentence describing what the feature does
- (optional) `implicit` — set when the feature is platform-level
  scaffolding that downstream tiers should treat as background, not
  as a direct user-visible commitment
- (optional) `comp_id` — substrate-root scope (default: `proj`)

## Steps

1. **Run the CLI subcommand.** From the repo root:

   ```bash
   ARGS=(--name "$name" --intent "$intent")
   [ "${implicit:-}" = "true" ] && ARGS+=(--implicit)
   python3 -m siege.cli add-feature "${ARGS[@]}"
   ```

   It appends the `<feature>` block to
   `feature_expansion/$comp_id/body.md`, re-derives the slim identity
   ledger (minting a fresh `feat_*` id for the new node), and flips
   the state JSON back to `drafted` with a fresh sha + nonce — any
   prior review or approval blocks are cleared because the body
   changed. Stdout is a JSON line with `feat_id` + `body_path` +
   `state_path` + `ids_path`.

   A non-zero exit means validation failed (e.g. the body has no
   `</features>` closing tag, or a `<feature>` with the same name
   already exists). Surface the error to the user; don't retry.

2. **Stage + commit + push.** One commit, three paths:
   `feature_expansion/$comp_id/body.md`,
   `state/feature_expansion/$comp_id.json`, and
   `ids/feature_expansion/$comp_id.json`:

   ```
   feature_expansion(add): <name>
   ```

   Push with `git push -u origin <branch>` (retry on network failure
   up to 4 times with 2s / 4s / 8s / 16s backoff).

3. **Echo the propagation hint.** Don't auto-open one — the user
   batches their edits and runs the propagation once at the end.
   One-line:

   ```
   next: /propagate_downstream from feature_expansion:$comp_id when ready
   ```

## Don't

- Don't redraft the whole feature_expansion body through an LLM —
  that's a different skill (`/modify_feature_expansion` if one exists,
  or `/regen_feature_expansion_with_feedback`).
- Don't auto-propagate. Manual propagation is the design — see the
  hint in step 3.
- Don't push to a branch other than the session's working branch.

## Output

One line: the minted `feat_id`, the commit sha, and the propagation
hint.
