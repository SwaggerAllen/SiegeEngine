"""Review-side context for the comparch tier.

Reuses the generator's ``build_regen_context`` / ``format_regen_context``
pipeline directly — zero drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.graph.regen_context import build_regen_context, format_regen_context
from backend.models.node import Node


@dataclass(frozen=True)
class ComparchContext:
    project_id: str
    component_id: str
    component_name: str
    component_kind: str
    target_is_foundation: bool
    context_kwargs: dict[str, Any]  # the rendered context bundle


def gather_comparch_context(db: Session, project_id: str, component_id: str) -> ComparchContext:
    comp_node = db.get(Node, component_id)
    if comp_node is None or comp_node.project_id != project_id:
        raise ValueError(f"Component {component_id!r} not found in project {project_id!r}")
    if comp_node.tier != "comp" or comp_node.parent_id is not None:
        raise ValueError(
            f"Node {component_id!r} is not a top-level comp (tier={comp_node.tier!r}, "
            f"parent_id={comp_node.parent_id!r})"
        )
    regen_ctx = build_regen_context(db, component_id)
    context_kwargs = format_regen_context(regen_ctx)
    return ComparchContext(
        project_id=project_id,
        component_id=component_id,
        component_name=comp_node.name,
        component_kind=comp_node.kind,
        target_is_foundation=bool(comp_node.is_foundation),
        context_kwargs=context_kwargs,
    )
