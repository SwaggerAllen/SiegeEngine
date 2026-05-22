"""Node manifests — the identity ledger of nodes a substrate file declares.

A *substrate file* is the unit of generation, draft → review → approve,
and one git commit: ``state/<tier>/<id>.json`` plus its body. A *node*
is a graph entity — a feature, a responsibility, a component. The four
decomposing tiers (``feature_expansion``, ``requirements``,
``sysarch``, ``comparch``) each produce a substrate file that
*declares many nodes* (the features / responsibilities / components /
subcomponents inside its body).

The manifest bridges the two. The *persisted* form — the **identity
ledger** at ``ids/<tier>/<id>.json`` — is slim: per node, only its
stable id and the key it carries forward by — the one fact that can't
be re-derived (ids are random and must stay stable across regens).
feature_expansion / requirements carry forward by the node ``<name>``;
sysarch / comparch by the ``alias`` attribute their body elements
declare. Every other node field (``kind`` / ``order`` / ``name`` /
``intent`` / ``implicit`` / ``feats`` / ``is_foundation``) is *not*
stored — the projection re-derives it from the body and joins it onto
the persisted ids. The in-memory ``Manifest`` this module hands back
is the full (rehydrated) node index; downstream context builders read
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
    keys (features add ``intent`` + ``implicit``; responsibilities add
    ``feats``; components / subcomponents add ``alias`` +
    ``is_foundation``). As read straight off disk by ``parse_manifest``
    the nodes are *slim* — ``id`` + the carry-forward key (``name`` for
    feature_expansion / requirements, ``alias`` for sysarch /
    comparch). Readers extract the keys they care about.
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
# sysarch / comparch declare children by an `alias` attribute on the
# opening tag — capture the attrs (group 1) alongside the inner body
# (group 2), since the `[^>]*` in the block scans above discards them.
_COMPONENT_BLOCK = re.compile(r"<component\b([^>]*)>(.*?)</component>", re.S)
_SUBCOMPONENT_BLOCK = re.compile(r"<subcomponent\b([^>]*)>(.*?)</subcomponent>", re.S)
_FEAT_REF = re.compile(r'<feat\s+id="([^"]+)"')
_ALIAS_ATTR = re.compile(r'\balias\s*=\s*"([^"]*)"')

#: Per-tier id prefix. ``comp_`` covers both top-level components
#: (sysarch) and subcomponents (comparch). The ``policy_*`` nodes the
#: v3 tier table also lists for sysarch/comparch are deferred — there
#: is no ``<policy>`` alias grammar to derive them from.
_ID_PREFIX = {
    "feature_expansion": "feat_",
    "requirements": "resp_",
    "sysarch": "comp_",
    "comparch": "comp_",
}

#: The node field each tier carries its id forward by across a regen.
#: feature/requirements have no alias — their ``<name>`` is the handle;
#: a sysarch/comparch ``<name>`` is a display title that can drift, so
#: the stable ``alias`` attribute is the carry-forward key instead.
_LEDGER_KEY = {
    "feature_expansion": "name",
    "requirements": "name",
    "sysarch": "alias",
    "comparch": "alias",
}

#: Tiers whose substrate body declares nodes (and so carries a ledger).
DECOMPOSING_TIERS = frozenset(_ID_PREFIX)


def _tag(name: str, block: str) -> str:
    """First ``<name>…</name>`` inner text in a block, stripped."""
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (name, name), block, re.S)
    return m.group(1).strip() if m else ""


def _alias_node(kind: str, order: int, attrs: str, inner: str) -> dict[str, Any]:
    """Build one sysarch/comparch node — ``alias`` from the opening-tag
    attributes, the rest from the block body."""
    m = _ALIAS_ATTR.search(attrs)
    return {
        "kind": kind,
        "order": order,
        "alias": m.group(1) if m else "",
        "name": _tag("name", inner),
        "is_foundation": "<foundation" in inner,
    }


def derive_manifest(
    substrate: Scope, body: str, body_sha256: str, prior: Manifest | None
) -> Manifest:
    """Derive a node manifest from a substrate body.

    A tolerant regex scan — the body XML allows raw ``<`` / ``&`` in
    text, so a non-greedy block scan is used, not a strict parser.
    Each ``<feature>`` / ``<responsibility>`` / ``<component>`` /
    ``<subcomponent>`` block becomes one node; node ids carry forward
    from ``prior`` by the tier's ledger key (``<name>`` for
    feature_expansion / requirements, the ``alias`` attribute for
    sysarch / comparch), so a regen keeps ids stable and a new or
    renamed node mints a fresh id.

    Only the decomposing tiers declare nodes — calling this for
    another tier is a programming error.
    """
    prefix = _ID_PREFIX.get(substrate.tier)
    if prefix is None:
        raise ValueError(f"tier {substrate.tier!r} does not declare an identity ledger")

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
    elif substrate.tier == "requirements":
        for i, blk in enumerate(_RESP_BLOCK.findall(body)):
            nodes.append(
                {
                    "kind": "responsibility",
                    "order": i,
                    "name": _tag("name", blk),
                    "feats": _FEAT_REF.findall(blk),
                }
            )
    elif substrate.tier == "sysarch":
        for i, (attrs, inner) in enumerate(_COMPONENT_BLOCK.findall(body)):
            nodes.append(_alias_node("component", i, attrs, inner))
    else:  # comparch
        for i, (attrs, inner) in enumerate(_SUBCOMPONENT_BLOCK.findall(body)):
            nodes.append(_alias_node("subcomponent", i, attrs, inner))

    key = _LEDGER_KEY[substrate.tier]
    prior_by_key: dict[str, str] = {}
    if prior is not None:
        for n in prior.nodes:
            prior_by_key.setdefault(str(n.get(key, "")).strip().lower(), str(n.get("id", "")))
    used: set[str] = set()
    for n in nodes:
        nid = prior_by_key.get(str(n[key]).strip().lower())
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

    Per node, only its id and carry-forward key are persisted (``name``
    for feature_expansion / requirements, ``alias`` for sysarch /
    comparch); every other field (``kind`` / ``order`` / ``intent`` /
    ``implicit`` / ``feats`` / ``is_foundation``) is dropped — the
    projection re-derives them from the body. Always stamps the current
    ``MANIFEST_SCHEMA_VERSION`` so a written file is consistently
    v2-slim. ``substrate`` is emitted with four keys (no ``phase`` —
    only the unphased arch tiers carry ledgers).
    """
    key = _LEDGER_KEY.get(m.substrate.tier, "name")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "substrate": {
            "tier": m.substrate.tier,
            "comp_id": m.substrate.comp_id,
            "parent_id": m.substrate.parent_id,
            "sub_id": m.substrate.sub_id,
        },
        "derived_from_sha256": m.derived_from_sha256,
        "nodes": [{"id": n["id"], key: n[key]} for n in m.nodes],
    }


def write_manifest(path: Path, m: Manifest) -> None:
    """Write the slim identity ledger to disk as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dump_manifest(m), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
