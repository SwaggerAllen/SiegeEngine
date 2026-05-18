# State JSON schema (v1)

Per-scope state lives at `state/<tier>/<id>.json` (top-level) or
`state/<tier>/<parent_id>/subs/<sub_id>.json` (sub-tier). Artifact bodies
live as separate markdown files referenced by `body_path` so they diff
cleanly in GitHub UI; state JSON carries `body_sha256` for drift detection.

Every state transition is exactly one git commit, containing the state
JSON file plus any body files it references. The MCP server reads state
JSON from git; skills write it.

## Schema

```json
{
  "schema_version": 1,
  "scope": {
    "tier": "feature_expansion | requirements | sysarch | comparch | subcomparch | impl | fanin",
    "comp_id": "comp_abc",
    "parent_id": "comp_parent",
    "sub_id": "sub_xyz"
  },
  "status": "absent | drafted | reviewed | approved",
  "draft": {
    "body_path": "comparch/comp_abc/body.md",
    "body_sha256": "a1b2c3...",
    "generated_at": "2026-05-18T03:14:00Z",
    "generator_metadata": {
      "thinking_effort": "max",
      "batch_id": "batch_01HXXXXX",
      "model": "claude-opus-4-7"
    },
    "prior_review_text": "<review>...</review>"
  },
  "review": {
    "body_path": "comparch/comp_abc/review.md",
    "body_sha256": "d4e5f6...",
    "reviewed_at": "2026-05-18T03:42:00Z",
    "score": 72,
    "reviewer_metadata": {
      "thinking_effort": "max",
      "model": "claude-opus-4-7"
    }
  },
  "approval": {
    "approved_at": "2026-05-18T04:10:00Z",
    "approved_by": "user@example.com"
  },
  "nonce": "01HXXXXXXXXXXXXXXXXXXXXXXX",
  "is_foundation": false
}
```

## Field semantics

- **`schema_version`** — bump on any breaking change. Server refuses to
  parse versions it doesn't know.
- **`scope`** — fully identifies the artifact. `tier` is always present.
  `comp_id` is present for tier scopes that key by component (everything
  except `feature_expansion`, which keys by feature id placed in
  `comp_id`). `parent_id` + `sub_id` are present for sub-tier scopes
  (subcomparch under a parent comparch).
- **`status`** — coarse-grained gate. Transitions are:
  - `absent → drafted` via a `draft-*` skill
  - `drafted → reviewed` via a `review-*` skill
  - `reviewed → drafted` via `regen-*-with-feedback` (carries
    `prior_review_text`)
  - `reviewed → approved` via `mark-approved`
- **`draft.body_path`** — relative to repo root. Convention:
  `<tier>/<id>/body.md` for top-level, `<tier>/<parent_id>/subs/<sub_id>/body.md`
  for subs. Feature expansion uses `feature_expansion/<feat_id>/body.md`.
- **`draft.body_sha256`** — sha256 of the body file's bytes. Drift detection:
  server recomputes on read; mismatch → repair skill.
- **`draft.prior_review_text`** — only present after at least one
  regen-with-feedback. Empty/missing on first draft.
- **`review.body_path`** — convention: sibling of body at
  `<tier>/<id>/review.md`.
- **`review.score`** — integer 0..100. Histogram + summary aggregations
  consume this.
- **`approval`** — final gate. Once present, downstream tiers can read
  this scope as part of their generation context.
- **`nonce`** — ULID-shaped string. Set by the writing skill. Server
  uses (scope, nonce) as an idempotency key: a duplicate commit with the
  same nonce within the dedup window is rejected.
- **`is_foundation`** — boolean. Lives in state JSON, not the path. Lets
  bottom-up traversal weight foundation comparchs differently without
  reorganizing the repo.

## Path layout

```
state/
  feature_expansion/<feat_id>.json
  requirements/<req_id>.json
  sysarch/<sec_id>.json
  comparch/<comp_id>.json
  subcomparch/<comp_id>/<sub_id>.json
  impl/<comp_id>/<sub_id>.json
  fanin/<comp_id>.json
  batches/<batch_id>.json
  cohorts/<cohort_id>.json

feature_expansion/<feat_id>/body.md
feature_expansion/<feat_id>/review.md
requirements/<req_id>/body.md
requirements/<req_id>/review.md
sysarch/<sec_id>/body.md
sysarch/<sec_id>/review.md
comparch/<comp_id>/body.md
comparch/<comp_id>/review.md
comparch/<comp_id>/subs/<sub_id>/body.md
comparch/<comp_id>/subs/<sub_id>/review.md
impl/<comp_id>/<sub_id>/body.md
impl/<comp_id>/<sub_id>/review.md
fanin/<comp_id>/body.md
fanin/<comp_id>/review.md
```

State files cluster under `state/` so the MCP server can load all state
in a single tree-walk per ref, then lazy-load bodies on demand.

## Batches and cohorts

Batches survive as state files. A multi-scope op (e.g. "regen all
comparch below score 70") produces N per-scope commits plus a final
batch summary commit:

```json
{
  "schema_version": 1,
  "batch_id": "batch_01HXXXXX",
  "op_type": "regen_below_threshold",
  "tier": "comparch",
  "threshold": 70,
  "scopes": [
    {"tier": "comparch", "comp_id": "comp_a"},
    {"tier": "comparch", "comp_id": "comp_b"}
  ],
  "status": "complete | partial | failed",
  "started_at": "...",
  "completed_at": "...",
  "commit_shas": ["abc123", "def456"]
}
```

Cohorts (curated subsets of scopes for batched review) have identical
shape with `op_type` of `cohort_<flavor>`.

## Idempotency window

Server keeps a per-ref dedup cache of `(scope, nonce)` tuples seen in
the last 24h (cleared on restart; the canonical record lives in git
history anyway). A duplicate write within the window is rejected at the
HTTP/MCP layer with a clear error so the skill can recover. After 24h,
duplicates are merged at the git layer (the second commit is a no-op if
the body sha matches).

## Drift detection

On every read, the server recomputes `body_sha256` from the file bytes
and compares against the value in state JSON. On mismatch, the read
still returns (the file is the source of truth for content), but a
warning is attached to the response and the `repair-state-drift` skill
is offered to the user.
