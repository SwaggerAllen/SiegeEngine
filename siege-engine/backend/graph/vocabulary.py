"""Project vocabulary node lookups.

Vocabulary entries are ``vocab_*`` nodes — a first-class node tier
carrying project-specific term definitions whose bodies live in
the project repo at ``vocab/<vocab_id>/body.md`` (v3 git-backed).
The dashboard reads the projected state via these helpers;
authoring happens in Claude Code via the ``/create_vocab`` skill.

Scoping lives on ``Node.parent_id``:
    * ``None`` — project-level; visible to every consumer.
    * a ``feat_*`` id — feature-local; visible to consumers
      reachable from that feature via the decomposition walk.

The reducer (``backend.graph.reducer._enforce_vocab_parent_constraint``)
rejects any attempt to parent a vocab node under a non-feature
node, so callers here can assume ``parent_id`` is either ``None``
or a ``feat_*`` id without re-checking.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.node import Node

VOCAB_TIER = "vocab"


def list_project_vocab(session: Session, project_id: str) -> list[Node]:
    """Return every project-level vocab node (``parent_id`` is NULL)."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
                Node.parent_id.is_(None),
            )
            .order_by(Node.name.asc())
        ).scalars()
    )


def list_feature_vocab(session: Session, project_id: str, feat_id: str) -> list[Node]:
    """Return every vocab node scoped to one specific feature."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
                Node.parent_id == feat_id,
            )
            .order_by(Node.name.asc())
        ).scalars()
    )


def list_all_vocab(session: Session, project_id: str) -> list[Node]:
    """Return every vocab node in the project, regardless of scope."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
            )
            .order_by(
                Node.parent_id.asc().nullsfirst(),
                Node.name.asc(),
            )
        ).scalars()
    )


def vocab_by_id(session: Session, vocab_id: str) -> Node | None:
    """Return the vocab node with ``id == vocab_id``, or ``None``."""
    node = session.get(Node, vocab_id)
    if node is None or node.tier != VOCAB_TIER:
        return None
    return node


def vocab_by_name(
    session: Session,
    project_id: str,
    name: str,
    *,
    parent_id: str | None = None,
) -> Node | None:
    """Look up a vocab entry by its term name within a specific scope."""
    if parent_id is None:
        return session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
                Node.name == name,
                Node.parent_id.is_(None),
            )
        ).scalar_one_or_none()
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == VOCAB_TIER,
            Node.name == name,
            Node.parent_id == parent_id,
        )
    ).scalar_one_or_none()
