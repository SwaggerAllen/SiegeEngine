"""Node manifests — the derived index of nodes a substrate file declares.

A *substrate file* is the unit of generation, draft → review → approve,
and one git commit: ``state/<tier>/<id>.json`` plus its body. A *node*
is a graph entity — a feature, a responsibility. The single-node arch
tiers (``feature_expansion``, ``requirements``) each produce one
substrate file that *declares many nodes* (the features /
responsibilities inside its body).

The manifest bridges the two. It is a *derived* index — computed from
the substrate body at draft time, written as its own file in the same
commit, and carried forward (node IDs stay stable across regens by
name match). Downstream context builders read the manifest's node
records instead of re-parsing body XML, and pull only the nodes a
scope actually needs.

Path: ``manifest/<tier>/<id>.json``, mirroring ``state/<tier>/<id>.json``
(see ``Scope.manifest_path``). The schema lives at
``docs/migration/state-schema.md``.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siege.state import Scope

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Manifest:
    """The node index for one substrate file.

    ``nodes`` are plain dicts: each carries at least ``id``, ``kind``,
    ``name`` and ``order``; tier-specific keys ride alongside (features
    add ``intent`` + ``implicit``, responsibilities add ``feats``).
    Readers extract the keys they care about.
    """

    schema_version: int
    substrate: Scope
    derived_from_sha256: str
    nodes: list[dict[str, Any]]

    def node(self, node_id: str) -> dict[str, Any] | None:
        for n in self.nodes:
            if n.get("id") == node_id:
                return n
        return None


def parse_manifest(raw: dict[str, Any]) -> Manifest:
    """Convert a raw dict (from ``json.loads`` or a git blob) to a Manifest."""
    version = raw.get("schema_version", MANIFEST_SCHEMA_VERSION)
    if version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported manifest schema_version {version!r}; "
            f"this server reads {MANIFEST_SCHEMA_VERSION}"
        )
    sub = raw["substrate"]
    substrate = Scope(
        tier=sub["tier"],
        comp_id=sub.get("comp_id"),
        parent_id=sub.get("parent_id"),
        sub_id=sub.get("sub_id"),
        phase=sub.get("phase"),
    )
    nodes = raw.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("manifest 'nodes' must be a list")
    return Manifest(
        schema_version=version,
        substrate=substrate,
        derived_from_sha256=raw.get("derived_from_sha256", ""),
        nodes=nodes,
    )


def load_manifest(path: Path) -> Manifest:
    """Read a manifest JSON file from disk."""
    return parse_manifest(json.loads(path.read_text(encoding="utf-8")))


# ---------------- derivation (write side) ----------------

_FEATURE_BLOCK = re.compile(r"<feature\b[^>]*>(.*?)</feature>", re.S)
_RESP_BLOCK = re.compile(r"<responsibility\b[^>]*>(.*?)</responsibility>", re.S)
_FEAT_REF = re.compile(r'<feat\s+id="([^"]+)"')
_ID_PREFIX = {"feature_expansion": "feat_", "requirements": "resp_"}

#: Tiers whose substrate body declares nodes (and so carries a manifest).
DECOMPOSING_TIERS = frozenset(_ID_PREFIX)


def _tag(name: str, block: str) -> str:
    """First ``<name>…</name>`` inner text in a block, stripped."""
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (name, name), block, re.S)
    return m.group(1).strip() if m else ""


def derive_manifest(
    substrate: Scope, body: str, body_sha256: str, prior: Manifest | None
) -> Manifest:
    """Derive a node manifest from a substrate body.

    A tolerant regex scan — the body XML allows raw ``<`` / ``&`` in
    text, so a non-greedy block scan is used, not a strict parser.
    Each ``<feature>`` / ``<responsibility>`` block becomes one node;
    node ids carry forward from ``prior`` by lowercased name (a regen
    keeps ids stable), and a new or renamed node mints a fresh id.

    Only the decomposing tiers (``feature_expansion``,
    ``requirements``) declare nodes — calling this for another tier is
    a programming error.
    """
    prefix = _ID_PREFIX.get(substrate.tier)
    if prefix is None:
        raise ValueError(f"tier {substrate.tier!r} does not declare a node manifest")

    nodes: list[dict[str, Any]] = []
    if substrate.tier == "feature_expansion":
        for i, blk in enumerate(_FEATURE_BLOCK.findall(body)):
            nodes.append(
                {
                    "kind": "feature",
                    "order": i,
                    "name": _tag("name", blk),
                    "intent": _tag("intent", blk),
                    "implicit": "<implicit" in blk,
                }
            )
    else:  # requirements
        for i, blk in enumerate(_RESP_BLOCK.findall(body)):
            nodes.append(
                {
                    "kind": "responsibility",
                    "order": i,
                    "name": _tag("name", blk),
                    "feats": _FEAT_REF.findall(blk),
                }
            )

    prior_by_name: dict[str, str] = {}
    if prior is not None:
        for n in prior.nodes:
            prior_by_name.setdefault(str(n.get("name", "")).strip().lower(), str(n.get("id", "")))
    used: set[str] = set()
    for n in nodes:
        nid = prior_by_name.get(str(n["name"]).strip().lower())
        if not nid or nid in used:
            nid = prefix + secrets.token_hex(4)
        used.add(nid)
        n["id"] = nid

    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        substrate=substrate,
        derived_from_sha256=body_sha256,
        nodes=nodes,
    )


def dump_manifest(m: Manifest) -> dict[str, Any]:
    """Serialize a Manifest to a JSON-ready dict. Stable key order.

    ``substrate`` is emitted with four keys (no ``phase`` — only the
    unphased arch tiers carry manifests).
    """
    return {
        "schema_version": m.schema_version,
        "substrate": {
            "tier": m.substrate.tier,
            "comp_id": m.substrate.comp_id,
            "parent_id": m.substrate.parent_id,
            "sub_id": m.substrate.sub_id,
        },
        "derived_from_sha256": m.derived_from_sha256,
        "nodes": m.nodes,
    }


def write_manifest(path: Path, m: Manifest) -> None:
    """Write a Manifest to disk as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dump_manifest(m), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
