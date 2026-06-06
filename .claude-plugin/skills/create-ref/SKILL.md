---
name: create-ref
description: Create a project reference (a supplemental content node — DSL spec, runbook, design memo, implementation guide) for downstream tiers to consume via reference edges. Writes the content to the project repo's refs/ folder, commits, pushes, and tells the backend. Use when the user says "add this as a ref", "ingest this guide as supplemental content", "/create_ref ...", or supplies material that's implementation detail rather than architectural content.
---

# Create a reference

This is the authoring entry point for **references** — supplemental
content nodes that downstream tiers (comparch, subcomparch, impl in
the default bundle) consume via reference edges in their bodies.

Refs are for implementation-detail material: DSL specifications,
deployment runbooks, design rationale memos, technology-specific
implementation guides. Architectural content belongs in chain tiers
(feature_expansion / requirements / sysarch); refs hold the kind of
material that affects *how* the chain implements its decisions, not
*what* the decisions are.

## Inputs

- `name` — human-readable name for the ref, e.g.
  `"Stripe API summary"`, `"PCI compliance checklist"`.
- `content` — the ref body. Supply as a path via `content_file`, or
  inline prose written to a temp file first.
- `project_id` — the project's id.
- (optional) `body_path` — override the default
  `refs/<ref_id>/body.md` location. Bundles with custom layouts may
  use this; the default bundle doesn't.
- (optional) `allow_existing` — when a ref with the same name
  already exists, return that ref's id instead of erroring. Useful
  for idempotent re-runs.

## Steps

1. **Materialize the content to a file.** If `content_file` is
   supplied, use it. Otherwise write the user's inline prose to
   `/tmp/ref_<sanitized_name>.md`.

2. **Run the CLI subcommand.** From the project repo root:

   ```bash
   ARGS=(
     --project-id "$project_id"
     --name "$name"
     --content-file "$content_file"
   )
   [ -n "${body_path:-}" ] && ARGS+=(--body-path "$body_path")
   [ "${allow_existing:-}" = "true" ] && ARGS+=(--allow-existing)
   python3 -m siege.cli create-ref "${ARGS[@]}"
   ```

   The CLI:
   - Pre-checks for an existing ref by name (idempotency).
   - Mints a fresh `ref_*` id locally.
   - Writes the content to `refs/<ref_id>/body.md` (or `body_path`).
   - `git add` + `git commit -m "refs: add <name> (<ref_id>)"`.
   - `git push` (skip with `--no-push` for local testing).
   - POSTs to the backend `/api/projects/<project_id>/references`
     endpoint with `{ref_id, name, body_sha, body_path}`.

   The backend records the ref node in its projection without
   calling the LLM — body content is whatever the agent (you,
   right now) wrote.

3. **Surface the result.** The CLI prints a single JSON line:

   ```json
   {"action":"create-ref","id":"ref_...","name":"...",
    "body_sha":"abc123...","body_path":"refs/ref_.../body.md"}
   ```

   Pass the `id` back to the user. If `preexisting: true` appears,
   the ref already existed and we returned its id without modifying
   it — surface that distinction to the user.

## Wiring the ref to consuming tiers

After creating a ref, it sits in the project's ref pool but isn't
consumed by anything until a downstream tier's body adds a
`<reference target="<ref_id>"/>` block. Two paths:

1. **Manual edit**: if the consuming tier has already drafted,
   open its body file and add the marker manually, then commit.
   The next read of that tier picks up the ref's content via the
   reference edge.

2. **Regen with hint**: re-run `/draft-comparch` (or the
   equivalent for the consuming tier) with feedback that names
   the new ref — e.g. `"Include refs/ref_XYZ when discussing
   billing API design"`. The LLM-driven draft will include the
   `<reference>` marker.

In the default bundle, refs are consumed by comparch and below.
Don't attach refs to sysarch or feature_expansion — those tiers
make architectural decisions, refs are implementation detail.

## Authentication

Reads `SIEGE_TOKEN` from env. Backend URL defaults to
`https://siege.strutco.io`, overridable via `SIEGE_API_BASE`. See
the dev-token panel at `/cheatsheet` for the JWT export command.

## Failure modes

- **422 "ref_id must match"**: locally minted id is malformed — file
  a bug, this should not happen.
- **409 "Reference named X already exists"**: a ref with the same
  name exists. Pass `--allow-existing` to use it instead of
  failing, or supply a different name.
- **404 "Project not found"**: confirm `--project-id` with the
  user.
- **`git push` failed**: local commit is intact; backend will not
  be able to fetch the body until the branch is pushed manually.

## Output

Always echo the ref's id and body path so the user knows what was
created and where they can find the content to edit it later.
