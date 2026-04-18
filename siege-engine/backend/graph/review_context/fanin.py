"""Review-side context for the fanin tier.

Reuses the generator's ``build_fanin_synthesis_context``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.graph.regen_context import build_fanin_synthesis_context
from backend.models.node import Node


@dataclass(frozen=True)
class FanInContext:
    project_id: str
    fanin_node_id: str
    owner_comp_id: str
    owner_comp_name: str
    synthesis_ctx: Any  # the dataclass returned by build_fanin_synthesis_context


def gather_fanin_context(db: Session, project_id: str, fanin_node_id: str) -> FanInContext:
    fanin_node = db.get(Node, fanin_node_id)
    if fanin_node is None or fanin_node.project_id != project_id:
        raise ValueError(f"Fan-in node {fanin_node_id!r} not found in project {project_id!r}")
    if fanin_node.tier != "fanin" or fanin_node.parent_id is None:
        raise ValueError(
            f"Node {fanin_node_id!r} is not a fanin with an owner "
            f"(tier={fanin_node.tier!r}, parent_id={fanin_node.parent_id!r})"
        )
    owner = db.get(Node, fanin_node.parent_id)
    if owner is None:
        raise ValueError(f"Fan-in {fanin_node_id!r} owner {fanin_node.parent_id!r} not found")
    synthesis_ctx = build_fanin_synthesis_context(db, owner.id)
    return FanInContext(
        project_id=project_id,
        fanin_node_id=fanin_node_id,
        owner_comp_id=owner.id,
        owner_comp_name=owner.name,
        synthesis_ctx=synthesis_ctx,
    )
