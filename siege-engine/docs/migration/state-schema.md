# State JSON schema (v1 + v2)

Per-scope state lives at `state/<tier>/<id>.json` (top-level) or
`state/<tier>/<parent_id>/subs/<sub_id>.json` (sub-tier). Artifact bodies
live as separate markdown files referenced by `body_path` so they diff
cleanly in GitHub UI; state JSON carries `body_sha256` for drift detection.

Every state transition is exactly one git commit, containing the state
JSON file plus any body files it references. The MCP server reads state
JSON from git; skills write it.

## Schema versions

- **v1** — the original schema (no `scope.phase`).
- **v2** — adds the `scope.phase` dimension for impl-tier phasing.
  Only `impl` and `fanin` scopes carry a phase; the five arch tiers
  never do.

The server parses **both** (`SUPPORTED_SCHEMA_VERSIONS = {1, 2}`).
There is no migration: a v1 file is a valid phase-`None` artifact and
parses unchanged. A writer emits `schema_version: 2` only when it
writes a *phased* (impl/fanin with a phase) scope; everything else
keeps emitting `1`. The version tracks the artifact's scope shape,
not a global epoch — re-dumping a v1 file keeps it v1.

## Schema

```json
{
  "schema_version": 2,
  "scope": {
    "tier": "feature_expansion | requirements | sysarch | comparch | subcomparch | impl | fanin",
    "comp_id": "comp_abc",
    "parent_id": "comp_parent",
    "sub_id": "sub_xyz",
    "phase": 2
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
  `comp_id` is the per-project scope id for top-level tiers
  (`feature_expansion`, `requirements`, `sysarch`, `comparch`, `fanin`).
  `parent_id` + `sub_id` are present for sub-tier scopes (subcomparch /
  impl under a parent comparch). The single-node arch tiers
  `feature_expansion` and `requirements` produce exactly one substrate
  file per project — the features / responsibilities they expand into
  are not separate files but *nodes*, indexed by a node manifest (see
  "Node manifests" below).
- **`scope.phase`** — integer phase, present only on `impl` and `fanin`
  scopes once impl-tier phasing is in play; `null`/absent everywhere
  else. An impl scope is keyed by `(parent_id, sub_id, phase)` — one
  subcomponent can have several impl nodes, one per phase. A `fanin`
  scope is keyed by `(comp_id, phase)`. See "Impl-tier phasing" below.
- **`status`** — coarse-grained gate. Transitions are:
  - `absent → drafted` via a `draft-*` skill
  - `drafted → reviewed` via a `review-*` skill
  - `reviewed → drafted` via `regen-*-with-feedback` (carries
    `prior_review_text`)
  - `reviewed → approved` via `mark-approved`
- **`draft.body_path`** — relative to repo root. Convention:
  `<tier>/<id>/body.md` for top-level, `<tier>/<parent_id>/subs/<sub_id>/body.md`
  for subs.
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
  feature_expansion/<comp_id>.json
  requirements/<comp_id>.json
  sysarch/<comp_id>.json
  comparch/<comp_id>.json
  subcomparch/<comp_id>/<sub_id>.json
  impl/<comp_id>/<sub_id>.json
  fanin/<comp_id>.json
  batches/<batch_id>.json
  cohorts/<cohort_id>.json

manifest/
  feature_expansion/<comp_id>.json
  requirements/<comp_id>.json

feature_expansion/<comp_id>/body.md
feature_expansion/<comp_id>/review.md
requirements/<comp_id>/body.md
requirements/<comp_id>/review.md
sysarch/<comp_id>/body.md
sysarch/<comp_id>/review.md
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
in a single tree-walk per ref, then lazy-load bodies on demand. Node
manifests cluster the same way under `manifest/`.

## Node manifests

A *substrate file* — `state/<tier>/<id>.json` plus its body — is the
unit of generation, the draft → review → approve cycle, and one git
commit. A *node* is a graph entity: a feature, a responsibility. The
two are not the same thing.

The single-node arch tiers `feature_expansion` and `requirements` each
produce exactly one substrate file per project, whose body *declares
many nodes* — every `<feature>` / `<responsibility>` inside it. The
**node manifest** is the derived index of those nodes:

```
manifest/feature_expansion/<comp_id>.json
manifest/requirements/<comp_id>.json
```

```json
{
  "schema_version": 1,
  "substrate": {"tier": "feature_expansion", "comp_id": "civic_platform"},
  "derived_from_sha256": "<sha256 of the body the manifest was derived from>",
  "nodes": [
    {"id": "feat_a1b2c3d4", "kind": "feature", "order": 0,
     "name": "Login", "intent": "Users sign in.", "implicit": false}
  ]
}
```

- The manifest is **derived, not authored** — a `draft-*` skill
  computes it by parsing the body it just composed and writes it in
  the *same commit* as the body + state JSON. No LLM and no human
  edits it directly.
- **Node ids** (`feat_*` / `resp_*`) are minted on first derivation
  and **carried forward by name** on every regen, so an id stays
  stable across regenerations; a new or renamed node mints a fresh id.
- **`derived_from_sha256`** ties the manifest to the exact body it was
  computed from. A mismatch against the live body means the manifest
  is stale — `mark-drafted` and `repair-state-drift` rebuild it.
- Per-tier node shapes: a `feature` node carries `name` + `intent` +
  `implicit`; a `responsibility` node carries `name` + `feats` (the
  `feat_*` ids it derives from).

Downstream context builders read manifests, never raw upstream bodies:
`requirements` pulls the feature nodes, `sysarch` pulls feature +
responsibility nodes, and `related_features_summary` + the phasing
plan walk `parent_resps → resp node.feats → feat node`. Each reader
pulls only the nodes a scope needs — not a whole body file.

## Impl-tier phasing (schema v2)

When a project is built in phases, the `impl` and `fanin` tiers gain a
`phase` dimension. The five arch tiers (feature_expansion …
subcomparch) are **never** phased — the whole design builds first;
phasing partitions only the implementation.

Phased path layout (`phase = N`):

```
state/impl/<comp_id>/p<N>/<sub_id>.json
impl/<comp_id>/subs/<sub_id>/p<N>/body.md
impl/<comp_id>/subs/<sub_id>/p<N>/review.md

state/fanin/<comp_id>/p<N>.json
fanin/<comp_id>/p<N>/body.md
fanin/<comp_id>/p<N>/review.md
```

A pre-phasing impl/fanin artifact (no `phase`) keeps the legacy
unphased layout (`state/impl/<comp_id>/<sub_id>.json`, etc.) — the
path methods are byte-identical when `phase` is `None`.

The phase dimension is driven by:

- **Phase registry** — `state/phases/<phase_id>.json`: an ordered
  (`order: int`) phase with a list of assigned `feature_ids`. Holds
  the user's release-planning intent.
- **Plan** — `state/plan.json`: a computed projection that derives,
  per phase, the impl nodes to build and their topological order.
  Recomputed from the registry + the comparch/subcomparch tiers; see
  the phasing plan for the `compute_plan` algorithm.

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
