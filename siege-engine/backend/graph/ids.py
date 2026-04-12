"""Stable ID scheme for v2 structured-model entities.

IDs have the form ``<kind>_<8 Crockford base32 chars>``, e.g.
``comp_c5h9m4p1``. The suffix is fully opaque — it is not derived
from the entity's name, because rename must not change identity.

The ``comp`` kind is tier-agnostic: both top-level components and
subcomponents use it so that promotion/demotion does not change the
ID. Lineage across structural operations is tracked in the graph
event log, not encoded in the ID.
"""

from __future__ import annotations

import secrets
from enum import Enum

from sqlalchemy.orm import Session

# Crockford base32 — 32 unambiguous characters, no I/L/O/U.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_SET = frozenset(_CROCKFORD)

SUFFIX_LENGTH = 8
COLLISION_RETRIES = 10


class Kind(str, Enum):
    """Entity kinds in the structured model ID vocabulary.

    See ``docs/architecture/v2-rearchitecture.md`` §ID scheme for the
    full list and what each kind means. Singletons (``expansion``,
    ``reqs``, ``sysarch``, ``manifest``) still use the same
    ``<kind>_<8 chars>`` form as the others — the suffix is decorative
    for one-per-project nodes but keeps call sites uniform.
    """

    FEAT = "feat"
    RESP = "resp"
    COMP = "comp"
    IMPL = "impl"
    PLAN = "plan"
    EDGE = "edge"
    EXPANSION = "expansion"
    REQS = "reqs"
    SYSARCH = "sysarch"
    MANIFEST = "manifest"
    FANIN = "fanin"


class InvalidIdError(ValueError):
    """Raised when an ID string does not match the scheme."""


class IdCollisionError(RuntimeError):
    """Raised when mint() cannot find a free suffix within retry budget."""


def _random_suffix() -> str:
    """Generate an 8-char Crockford base32 suffix."""
    return "".join(secrets.choice(_CROCKFORD) for _ in range(SUFFIX_LENGTH))


def mint(db: Session, kind: Kind) -> str:
    """Mint a new stable ID of the given kind.

    Checks the ``nodes`` and ``edges`` tables for collisions and retries
    up to ``COLLISION_RETRIES`` times. The 40-bit suffix makes collisions
    vanishingly rare in practice, but we retry anyway to be defensive.
    """
    # Lazy import to avoid circular imports with backend.models.
    from backend.models.node import Edge, Node

    for _ in range(COLLISION_RETRIES):
        candidate = f"{kind.value}_{_random_suffix()}"
        # Check both tables; comp/feat/resp/impl live in nodes, edge lives in edges.
        node_hit = db.query(Node.id).filter(Node.id == candidate).first()
        edge_hit = db.query(Edge.id).filter(Edge.id == candidate).first()
        if node_hit is None and edge_hit is None:
            return candidate
    raise IdCollisionError(
        f"Failed to mint a unique {kind.value} ID after {COLLISION_RETRIES} attempts"
    )


def validate(id_str: str) -> tuple[Kind, str]:
    """Validate an ID and return its (kind, suffix) components.

    Raises :class:`InvalidIdError` on any format violation.
    """
    if not isinstance(id_str, str):
        raise InvalidIdError(f"ID must be a string, got {type(id_str).__name__}")
    try:
        kind_str, suffix = id_str.split("_", 1)
    except ValueError as exc:
        raise InvalidIdError(f"ID missing underscore separator: {id_str!r}") from exc
    try:
        kind = Kind(kind_str)
    except ValueError as exc:
        raise InvalidIdError(f"Unknown kind prefix in ID {id_str!r}: {kind_str!r}") from exc
    if len(suffix) != SUFFIX_LENGTH:
        raise InvalidIdError(
            f"ID suffix must be {SUFFIX_LENGTH} chars, got {len(suffix)}: {id_str!r}"
        )
    if not all(ch in _CROCKFORD_SET for ch in suffix):
        raise InvalidIdError(f"ID suffix contains non-Crockford chars: {id_str!r}")
    return kind, suffix
