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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siege_mcp.state import Scope

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
