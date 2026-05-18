# MCP tool surface (initial)

The MCP server is read-only. Every tool takes `ref` as its first
parameter (branch name or sha). On every read the server does
`git fetch origin <ref>` with a ~2s per-ref debounce, then reads from
the fetched ref's tree. No write tools — skills commit + push directly.

## Reads

### `list_refs()`

Returns:

```json
{
  "refs": [
    {"name": "main", "head_sha": "abc123", "head_subject": "..."},
    {"name": "feat-foo", "head_sha": "def456", "head_subject": "..."}
  ]
}
```

Used by the dashboard branch selector and by skills that need to enumerate
candidate refs.

### `get_state(ref, scope)`

Returns the parsed state JSON for one scope, plus a `drift` block if the
body sha doesn't match.

```python
get_state(ref="feat-foo", scope={"tier": "comparch", "comp_id": "comp_a"})
```

### `list_tier(ref, tier, filters=None)`

Returns all state JSONs for a tier on a ref, optionally filtered.

```python
list_tier(ref="main", tier="comparch", filters={"status": "drafted"})
list_tier(ref="main", tier="comparch", filters={"max_score": 70})
```

Filters supported: `status`, `min_score`, `max_score`, `is_foundation`,
`approved`, `has_review`.

### `get_generation_context(ref, tier, scope)`

Returns the prompt bundle a draft skill needs. Built by porting
`backend/graph/regen_context.py` per-tier. Bundle includes:

- The tier's generator instruction text
- Parent-tier fragments relevant to this scope
- Sibling artifacts whose public APIs / contracts the new artifact must
  respect (e.g. sibling comparch pubapis when drafting a new comparch)
- Project-wide sysarch sections (for comparch+)
- Related expanded features (for comparch+)
- Optional `prior_review_text` if the state is in `reviewed` and the skill
  is regen-with-feedback

Returns:

```json
{
  "instructions": "...",
  "parent_fragments": [...],
  "sibling_pubapis": [...],
  "project_sysarch_sections": [...],
  "related_features": [...],
  "prior_review_text": "...",
  "scope": {...},
  "ref": "main",
  "ref_head_sha": "abc123"
}
```

### `get_review_context(ref, tier, scope, draft_sha)`

Returns the reviewer-side bundle. Different from generation context: the
reviewer sees the draft body itself plus the artifacts the draft was
supposed to be consistent with. `draft_sha` (= `draft.body_sha256` from
state) pins which draft the review applies to — re-drafts produce new
shas and need new reviews.

### `get_review_summary(ref, tier)`

Returns score histogram + per-scope scores for a tier:

```json
{
  "tier": "comparch",
  "histogram": {"0-9": 0, "10-19": 1, ..., "90-100": 3},
  "scopes": [
    {"comp_id": "comp_a", "score": 87, "status": "reviewed"},
    {"comp_id": "comp_b", "score": 62, "status": "reviewed"},
    {"comp_id": "comp_c", "score": null, "status": "drafted"}
  ],
  "summary_text": "..."
}
```

### `get_structure_summary(ref, tier)`

Returns the topological structure of a tier — comparchs and their subs,
dependency edges, foundation markers. Used by orchestrator commands that
compute traversal order.

### `list_batches(ref, filters=None)`

Returns batch state files on a ref, optionally filtered by `status`,
`op_type`, `tier`, date range.

### `validate_artifact(ref, tier, scope, body)`

Validates a candidate artifact body before a skill commits it. Runs the
tier-appropriate parser (XML / markdown sections / dep graph) and returns:

```json
{
  "ok": true,
  "errors": [],
  "warnings": [...],
  "extracted_metadata": {...}
}
```

A skill calls this between LLM completion and `git commit`. If `ok` is
false, the skill loops back to the LLM with the errors as feedback rather
than committing junk.

## Auth

JWT auth ported simplified from `backend/auth/service.py`. The HTTP
transport always requires a valid JWT (frontend has one already from the
existing dashboard login). The MCP transport's auth model depends on CC's
MCP-over-HTTP story and is settled during Phase 0 plugin install
validation — if CC passes a header, we accept the same JWT; if not, the
MCP transport binds to localhost only and the user proxies via SSH or
tailscale.

## Caching

Per (project, ref, head_sha) tuple, the server keeps an in-memory
`GitView` snapshot. `GitView` lazy-loads bodies on first access and
caches them. When `git fetch` reveals a new head_sha for a ref, the old
`GitView` is dropped. TTL on idle views: 10 minutes.

## Versioning

The MCP tool surface is versioned via the server's MCP protocol
declaration. Breaking changes bump the minor version and ship with a
deprecation window. Frontend pins to a major version.
