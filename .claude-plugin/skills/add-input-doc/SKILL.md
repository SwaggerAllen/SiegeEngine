---
name: add-input-doc
description: Register a project input document (project doc, domain spec, style guide, etc.) so the chain's extraction tiers can read it. Writes the content to the project repo's inputs/ folder, commits it, pushes, and tells the backend the new doc exists. Use when the user supplies a seed document, says "add this as the project doc", "ingest this style guide", or invokes /add_input_doc.
---

# Add an input document

This is the authoring entry point for **input documents** — the prose
content extraction tiers (feature_expansion, requirements, sysarch in
the default bundle) read to extract project scope. Use it when the
user supplies a document and wants it ingested into the project's
input slots.

In siege today, the only input role the default bundle uses is
`project_doc` (the primary project description). Catapult bundles can
declare additional roles like `domain_spec`, `style_guide`, etc.; the
skill is generic over the role name.

## Inputs

- `role` — bundle-declared role name (default bundle: `project_doc`)
- `name` — human-readable name for the document, e.g. `"Initial spec"`
- `content` — the document body. Supply as a path to a local file via
  `content_file`, or as inline prose the skill should write to a
  temp file first.
- `project_id` — the project's id (the dashboard URL contains it).
- (optional) `body_path` — override the default
  `inputs/<role>.md` location. Bundles with custom layouts may use
  this; the default bundle does not.

## Steps

1. **Materialize the content to a file.** If `content_file` is
   supplied, use it directly. If the user pasted inline prose, write
   it to a temp file (e.g. `/tmp/input_<role>.md`) so the CLI has
   something to read.

2. **Run the CLI subcommand.** From the project repo root:

   ```bash
   ARGS=(
     --project-id "$project_id"
     --role "$role"
     --name "$name"
     --content-file "$content_file"
   )
   [ -n "${body_path:-}" ] && ARGS+=(--body-path "$body_path")
   python3 -m siege.cli add-input-doc "${ARGS[@]}"
   ```

   The CLI:
   - Reads the content file.
   - Writes it to `inputs/<role>.md` (or `body_path` if supplied) in
     the local repo.
   - `git add` + `git commit` with message
     `inputs: add <role> (<name>)`.
   - `git push` (skip with `--no-push` for local-only testing).
   - Resolves the new commit's sha.
   - POSTs to the backend's `/api/projects/<project_id>/input-documents`
     endpoint with `{ role, name, body_sha, body_path }`.

   The backend records the input document's row + git coordinates in
   its `input_documents` projection. Server-side readers
   (`expand_single_feature`, the dashboard) fetch the content from
   git when they need it.

3. **Surface the result.** The CLI prints a single JSON line:

   ```json
   {"action":"add-input-doc","id":"doc_...","role":"project_doc",
    "name":"Initial spec","body_sha":"abc123...",
    "body_path":"inputs/project_doc.md"}
   ```

   Pass the `id` back to the user as a confirmation that the input is
   registered.

## Authentication

The CLI reads `SIEGE_TOKEN` from the environment to authenticate
against the backend. If the user hasn't set it yet:

1. Direct them to `https://siege.strutco.io/cheatsheet`.
2. The dev-token panel at the top shows their JWT in
   copy-paste-ready `export SIEGE_TOKEN=...` form.
3. Run that export in the same shell, then retry.

The backend URL defaults to `https://siege.strutco.io` and is
overridable via `SIEGE_API_BASE` for development instances.

## Failure modes

- **Backend rejects with 404 "Project not found"**: the
  `--project-id` doesn't match an existing project. Confirm the id
  with the user.
- **Backend rejects with 422 "role cannot be empty"**: the supplied
  `role` is blank.
- **`git push` failed**: the local commit landed but didn't reach
  the remote. The CLI prints a warning but still attempts the
  backend call; backend reads will 404 on the body fetch until the
  user pushes manually.
- **Content file missing**: CLI exit code 2 with a clear error.

## Output

Always echo the registered doc's id and the body path so the user
knows where to find the content if they want to edit it manually.
