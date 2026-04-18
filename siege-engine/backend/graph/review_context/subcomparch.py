"""Review-side context for the subcomparch tier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.graph.regen_context import (
    build_regen_context,
    format_regen_context_for_sub,
)
from backend.models.node import Node


@dataclass(frozen=True)
class SubcomparchContext:
    project_id: str
    sub_id: str
    sub_name: str
    parent_comp_id: str
    context_kwargs: dict[str, Any]


def gather_subcomparch_context(db: Session, project_id: str, sub_id: str) -> SubcomparchContext:
    sub_node = db.get(Node, sub_id)
    if sub_node is None or sub_node.project_id != project_id:
        raise ValueError(f"Subcomponent {sub_id!r} not found in project {project_id!r}")
    if sub_node.tier != "comp" or sub_node.parent_id is None:
        raise ValueError(
            f"Node {sub_id!r} is not a subcomponent (tier={sub_node.tier!r}, "
            f"parent_id={sub_node.parent_id!r})"
        )
    regen_ctx = build_regen_context(db, sub_id)
    context_kwargs = format_regen_context_for_sub(regen_ctx)
    return SubcomparchContext(
        project_id=project_id,
        sub_id=sub_id,
        sub_name=sub_node.name,
        parent_comp_id=sub_node.parent_id,
        context_kwargs=context_kwargs,
    )
