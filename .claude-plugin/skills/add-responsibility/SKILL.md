---
name: add-responsibility
description: Append a new responsibility to the requirements substrate body. Mechanical, no LLM — wraps `siege add-responsibility`. Use when the user says "add resp X", "/add_resp X", or asks to extend the responsibility set without redrafting. Mints a fresh `resp_*` id and validates any `--feat-ids` against the feature_expansion ledger.
---

# Add a responsibility

Extends the requirements tier by one responsibility node. The
responsibility may reference zero or more existing `feat_*` ids
(validated against the feature_expansion ledger so dangling refs
never land in the body).

## Inputs

- `name` — short name for the new responsibility, e.g.
  `"Saved Search Persistence"`
- (optional) `feat_ids` — comma-separated `feat_*` ids the resp
  serves. Validated against `ids/feature_expansion/$comp_id.json`;
  an unknown id is a hard error. Empty list (omit the flag) is
  permitted — owned platform work that traces to no specific feature.
- (optional) `comp_id` — substrate-root scope (default: `proj`)

## Steps

1. **Run the CLI subcommand:**

   ```bash
   ARGS=(--name "$name")
   [ -n "${feat_ids:-}" ] && ARGS+=(--feat-ids "$feat_ids")
   python3 -m siege.cli add-responsibility "${ARGS[@]}"
   ```

   It appends `<responsibility><name>...</name><feats>...</feats></responsibility>`
   to `requirements/$comp_id/body.md` (with the `<feat id="..."/>` refs
   inlined), re-derives the ledger (minting a fresh `resp_*` id), and
   flips state back to `drafted`. Stdout is a JSON line with `resp_id`
   + `feat_ids` (echoed back) + the three paths it touched.

   Non-zero exits: missing `</requirements>` closing tag, duplicate
   name, or unknown feat_id.

2. **Stage + commit + push** — three paths
   (`requirements/.../body.md`, the state JSON, the ledger):

   ```
   requirements(add): <name>
   ```

3. **Echo the propagation hint:**

   ```
   next: /propagate_downstream from requirements:$comp_id when ready
   ```

## Don't

- Don't reference a feat_id that isn't in the feature_expansion
  ledger — the CLI rejects this. If the feature doesn't exist yet,
  add it first via `/add_feature`.
- Don't redraft the whole requirements body to "fit" the new resp;
  the new resp lands as an inert block, and the responsibility-to-comp
  mapping is sysarch's call (propagation flows downward into sysarch).
- Don't auto-propagate.

## Output

One line: minted `resp_id`, the commit sha, the propagation hint.
