"""Node manifests — the identity ledger of nodes a substrate file declares.

A *substrate file* is the unit of generation, draft → review → approve,
and one git commit: ``state/<tier>/<id>.json`` plus its body. A *node*
is a graph entity — a feature, a responsibility. The single-node arch
tiers (``feature_expansion``, ``requirements``) each produce one
substrate file that *declares many nodes* (the features /
responsibilities inside its body).

The manifest bridges the two. The *persisted* form — the **identity
ledger** at ``ids/<tier>/<id>.json`` — is slim: only the id↔name
binding per node, the one fact that can't be re-derived (ids are
random and must stay stable across regens, carried forward by name
match). The projectable node fields (``intent`` / ``feats`` /
``implicit`` / ``order`` / ``kind``) are *not* stored — the
projection re-derives them from the body and joins them onto the
persisted ids. The in-memory ``Manifest`` this module hands back is
the full (rehydrated) node index; downstream context builders read
its node records and pull only the nodes a scope needs.

Persisted at ``ids/<tier>/<id>.json``, mirroring
``state/<tier>/<id>.json`` (see ``Scope.ids_path``). The schema
lives at ``docs/migration/state-schema.md``.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siege.state import Scope

#: Schema version freshly-written ledgers carry.
MANIFEST_SCHEMA_VERSION = 2

#: Versions ``parse_manifest`` accepts. ``1`` is the legacy fat
#: manifest (pre-slim) — still read so a ``manifest/`` tree migrates
#: to ``ids/`` with a plain ``git mv``; the next write upgrades it.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})


@dataclass(frozen=True)
class Manifest:
    """The in-memory node index for one substrate file.

    ``nodes`` are plain dicts. As produced by ``derive_manifest`` (and
    after the projection rehydrates a persisted ledger) each node is
    *full*: ``id``, ``kind``, ``name``, ``order`` plus tier-specific
    keys (features add ``intent`` + ``implicit``, responsibilities add
    ``feats``). As read straight off disk by ``parse_manifest`` the
    nodes are *slim* — only ``id`` + ``name``, the identity ledger.
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
    """Convert a raw dict (from ``json.loads`` or a git blob) to a Manifest.

    Reads both schema versions: ``2`` is the slim identity ledger
    (id+name); ``1`` is the legacy fat manifest, still accepted so a
    pre-slim ``manifest/`` tree migrates with a plain ``git mv`` —
    rehydration re-derives the full node fields from the body either
    way, and the next write upgrades the file to v2.
    """
    version = raw.get("schema_version", MANIFEST_SCHEMA_VERSION)
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported manifest schema_version {version!r}; "
            f"this server reads {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
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
    """Serialize a Manifest to a JSON-ready dict — the slim identity ledger.

    Only the id↔name binding per node is persisted; the projectable
    fields (``kind`` / ``order`` / ``intent`` / ``implicit`` /
    ``feats``) are dropped — the projection re-derives them from the
    body. Always stamps the current ``MANIFEST_SCHEMA_VERSION`` so a
    written file is consistently v2-slim. ``substrate`` is emitted with
    four keys (no ``phase`` — only the unphased arch tiers carry ledgers).
    """
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "substrate": {
            "tier": m.substrate.tier,
            "comp_id": m.substrate.comp_id,
            "parent_id": m.substrate.parent_id,
            "sub_id": m.substrate.sub_id,
        },
        "derived_from_sha256": m.derived_from_sha256,
        "nodes": [{"id": n["id"], "name": n["name"]} for n in m.nodes],
    }


def write_manifest(path: Path, m: Manifest) -> None:
    """Write the slim identity ledger to disk as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dump_manifest(m), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
