---
name: repair-state-drift
description: Recompute body_sha256 for a scope's state JSON when the MCP server reports drift. Use when `get_state` returns a `drift` block on a scope you trust the body of — this skill writes a new state JSON with the correct sha and bumps nonce.
---

# Repair state JSON drift

Drift means the state JSON's recorded `body_sha256` doesn't match the
actual sha256 of the body file's bytes on the ref. This usually means
a body was edited without re-running the draft skill (or a merge
created a divergent body without a state update). The repair is to
recompute the sha and write a new state JSON; for the single-node arch
tiers (`feature_expansion`, `requirements`) it also rebuilds the
derived node manifest, which the same body edit left stale.

## Inputs

- `ref`, `tier`, `comp_id` (or `parent_id` + `sub_id`)
- (optional) `phase` — required to locate a phased `impl` / `fanin`
  node's state JSON; see "Phased nodes" below. Omit for arch tiers.
- (optional) `expected_status` — if set, the skill will refuse to
  repair if the state's status doesn't match. Defaults to no check.

## Steps

1. Read the existing state JSON at the conventional state path (for a
   phased impl/fanin node use the `p<N>` layout below).
2. Read the body file at `draft.body_path` and `review.body_path` (if
   the review block is present). These paths come from the state JSON
   itself — they are already correct, phased or not; no reconstruction.
3. Recompute sha256 for each.
4. Update the `body_sha256` fields where they're stale. Don't touch
   any other field except `nonce` (mint fresh) — in particular leave
   `schema_version` and `scope.phase` exactly as they are.
5. **Re-derive the node manifest** — `feature_expansion` and
   `requirements` only; the step self-skips for every other tier.
   The manifest at `manifest/<tier>/$comp_id.json` is derived from
   the body, so a body that drifted left the manifest stale too — and
   a scope that predates manifests has none at all, which this step
   backfills. Rebuild it from the trusted body with
   `derived_from_sha256` set to the recomputed body sha. Node ids
   carry forward from the prior manifest by name; a new or renamed
   node mints a fresh id. Pass `$tier`, `$comp_id`, the body path
   from `draft.body_path`, and the recomputed body sha:

   ```bash
   python3 - "$tier" "$comp_id" "$BODY_PATH" "$BODY_SHA" <<'PY'
import json, os, re, secrets, sys

tier, comp_id, body_path, body_sha = sys.argv[1:5]
if tier not in ("feature_expansion", "requirements"):
    print(json.dumps({"manifest": "not applicable for tier " + tier}))
    raise SystemExit(0)

text = open(body_path, encoding="utf-8").read()
def tag(name, s):
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (name, name), s, re.S)
    return m.group(1).strip() if m else ""

nodes = []
if tier == "feature_expansion":
    prefix = "feat_"
    for i, blk in enumerate(re.findall(r"<feature\b[^>]*>(.*?)</feature>", text, re.S)):
        nodes.append({"kind": "feature", "order": i, "name": tag("name", blk),
                      "intent": tag("intent", blk), "implicit": "<implicit" in blk})
else:
    prefix = "resp_"
    for i, blk in enumerate(re.findall(r"<responsibility\b[^>]*>(.*?)</responsibility>", text, re.S)):
        nodes.append({"kind": "responsibility", "order": i, "name": tag("name", blk),
                      "feats": re.findall(r'<feat\s+id="([^"]+)"', blk)})

manifest_path = "manifest/%s/%s.json" % (tier, comp_id)
prior_ids = {}
if os.path.exists(manifest_path):
    for n in json.loads(open(manifest_path).read()).get("nodes", []):
        prior_ids.setdefault(n.get("name", "").strip().lower(), n.get("id"))
used = set()
for n in nodes:
    nid = prior_ids.get(n["name"].strip().lower())
    if not nid or nid in used:
        nid = prefix + secrets.token_hex(4)
    used.add(nid)
    n["id"] = nid

manifest = {"schema_version": 1,
            "substrate": {"tier": tier, "comp_id": comp_id, "parent_id": None, "sub_id": None},
            "derived_from_sha256": body_sha, "nodes": nodes}
os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
open(manifest_path, "w").write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps({"manifest_path": manifest_path, "node_count": len(nodes)}))
PY
   ```
6. Commit one commit — stage the rebuilt manifest alongside the
   state JSON when step 5 produced one:
   `repair(<tier>/$id): recompute body_sha256 (drift)`
7. Push.

## Phased nodes

When `tier` is `impl` or `fanin` and the node is phased, supply the
`phase` input — the state JSON lives at a `p<N>` path:

| tier  | unphased state path | phased (`phase=N`) state path |
|-------|---------------------|--------------------------------|
| impl  | `state/impl/<parent>/<sub>.json` | `state/impl/<parent>/pN/<sub>.json` |
| fanin | `state/fanin/<comp>.json` | `state/fanin/<comp>/pN.json` |

## Don't

- Don't repair drift on an `approved` scope without explicit user
  confirmation — drift on an approved artifact usually means
  something more serious is wrong (a merge that mangled content)
  and silently recomputing the sha papers over it.

## Output

What changed (old sha → new sha for each file) + commit sha.
