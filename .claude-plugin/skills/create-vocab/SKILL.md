---
name: create-vocab
description: Create a project vocabulary entry — a project-specific term with a structured definition that downstream tiers use consistently. Writes content to the project repo's vocab/ folder, commits, pushes, and tells the backend. Use when the user supplies a glossary term + definition, says "add this as vocab", or invokes /create_vocab.
---

# Create a vocabulary entry

This is the authoring entry point for **vocabulary** — project-
specific terms with definitions that downstream tier prompts use to
keep terminology consistent across the chain. Use when the user
supplies a glossary term and wants it ingested into the project's
vocab pool.

Vocab entries are typically short structured blocks: term name,
one-paragraph definition, optional disambiguation note, optional
see-also cross-references. The chain reads them as supplemental
context — every generation prompt that wires vocab into its
context walk receives the relevant terms as Liquid variables.

## Inputs

- `name` — the term, e.g. `"billing cycle"`, `"card-on-file"`.
- `content` — the structured definition. Supply as a path via
  `content_file`, or as inline prose written to a temp file.
- `project_id` — the project's id.
- (optional) `body_path` — override the default
  `vocab/<vocab_id>/body.md`.
- (optional) `allow_existing` — when a vocab entry with the same
  name exists, return its id instead of erroring.

## Steps

1. **Materialize the content to a file.** If `content_file` is
   supplied, use it. Otherwise write the inline prose to
   `/tmp/vocab_<sanitized_name>.md`.

2. **Run the CLI subcommand.** From the project repo root:

   ```bash
   ARGS=(
     --project-id "$project_id"
     --name "$name"
     --content-file "$content_file"
   )
   [ -n "${body_path:-}" ] && ARGS+=(--body-path "$body_path")
   [ "${allow_existing:-}" = "true" ] && ARGS+=(--allow-existing)
   python3 -m siege.cli create-vocab "${ARGS[@]}"
   ```

   The CLI:
   - Pre-checks for an existing entry by name.
   - Mints a fresh `vocab_*` id locally.
   - Writes the content to `vocab/<vocab_id>/body.md`.
   - `git add` + commit with `"vocab: add <name> (<vocab_id>)"`.
   - Pushes (skip with `--no-push`).
   - POSTs to `/api/projects/<project_id>/vocabulary`.

3. **Surface the result.** Single JSON line:

   ```json
   {"action":"create-vocab","id":"vocab_...","name":"...",
    "body_sha":"abc123...","body_path":"vocab/vocab_.../body.md"}
   ```

   `preexisting: true` if the entry already existed and
   `--allow-existing` returned its id.

## Body grammar

The default bundle expects vocab bodies to be `<vocab-entry>`
elements with `<name>`, `<definition>`, optional
`<disambiguation>`, and optional `<see-also target="..."/>` blocks.
A minimal entry:

```markdown
<vocab-entry>
  <name>billing cycle</name>
  <definition>
    The 30-day period between automatic charges on a subscription.
    Resets when a customer changes plans or when an explicit
    proration event lands.
  </definition>
</vocab-entry>
```

## Authentication

`SIEGE_TOKEN` from env; `SIEGE_API_BASE` overrides the default
`https://siege.strutco.io`.

## Failure modes

- **422 "vocab_id must match"**: malformed id, should not happen.
- **409 "Vocab named X already exists"**: pass `--allow-existing`
  to use it, or supply a different name.
- **404 "Project not found"**: confirm `--project-id`.
- **`git push` failed**: local commit landed; backend reads will
  404 on the body fetch until the branch is pushed.

## Output

Echo the entry's id and body path so the user can edit the file
later if needed.
