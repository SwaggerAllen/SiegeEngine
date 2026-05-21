---
name: mark-drafted
description: Manually transition a scope's state to `drafted` after an out-of-band body edit. Use only when you've hand-edited a body.md file and need to re-sync state JSON (recompute body_sha256, bump nonce, set status). For normal drafts, use the per-tier `draft-*` skill instead — this is a repair tool.
---

# Mark a scope as drafted

Use this when you've manually edited a body.md outside of a `draft-*`
skill flow and need to bring state JSON back in sync. Normal drafts
should go through `draft-<tier>` which mints the state JSON for you.

## Inputs

- `ref` — git ref
- `tier` — one of feature_expansion / requirements / sysarch / comparch
  / subcomparch / impl / fanin
- `comp_id` and/or `parent_id` + `sub_id` per the tier's scope shape
- (optional) `phase` — required for a phased `impl` / `fanin` node;
  see "Phased nodes" below. Omit for the five arch tiers.

## Steps

1. Locate the body at the conventional path
   (`<tier>/$comp_id/body.md` or `<tier>/$parent_id/subs/$sub_id/body.md`;
   for a phased impl/fanin node use the `p<N>` layout below).
2. Compute `body_sha256` of the file contents.
3. Read the existing state JSON at the conventional state path.
4. Update:
   - `status` = `"drafted"`
   - `draft.body_sha256` = the new hash
   - `draft.generated_at` = now (UTC ISO-8601)
   - Mint a fresh `nonce`
   - Clear `review` and `approval` blocks (they no longer apply)
   - Leave `schema_version` and `scope.phase` exactly as they are.
5. **Re-derive the node manifest** — `feature_expansion` and
   `requirements` only; the step self-skips for every other tier. A
   hand body edit can add, remove, or rename features /
   responsibilities, so the manifest at
   `manifest/<tier>/$comp_id.json` is stale and must be rebuilt from
   the edited body. Node ids carry forward from the prior manifest by
   name (stable across the edit); a new or renamed node mints a fresh
   id. Pass `$tier`, `$comp_id`, and the `body_sha256` from step 2:

   ```bash
   BODY_PATH="$tier/$comp_id/body.md"
   BODY_SHA="<body_sha256 from step 2>"
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
6. Commit + push one commit — stage the rebuilt manifest alongside
   the state JSON when step 5 produced one:
   `mark-drafted(<tier>/$id): manual body edit`

## Phased nodes

When `tier` is `impl` or `fanin` and the node is phased, supply the
`phase` input — the node is keyed by `phase` and the on-disk layout
differs from the unphased (legacy) one:

| tier  | unphased state · body | phased (`phase=N`) state · body |
|-------|-----------------------|----------------------------------|
| impl  | `state/impl/<parent>/<sub>.json` · `impl/<parent>/subs/<sub>/body.md` | `state/impl/<parent>/pN/<sub>.json` · `impl/<parent>/subs/<sub>/pN/body.md` |
| fanin | `state/fanin/<comp>.json` · `fanin/<comp>/body.md` | `state/fanin/<comp>/pN.json` · `fanin/<comp>/pN/body.md` |

`review.md` sits beside `body.md`. A phased node's state JSON carries
`schema_version: 2` and `scope.phase = N` — preserve both.

## Output

Commit sha + one-line summary of what changed in the state JSON.
