"""Review-side context for the impl tier.

Impl's owner is the parent comp/sub (``node.parent_id``).
The review job payload carries ``node_id`` = the impl node;
we resolve ``owner_id`` from the impl's ``parent_id`` and feed
it to ``build_regen_context`` like the generator does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.graph.regen_context import (
    build_regen_context,
    format_regen_context_for_impl,
)
from backend.models.node import Node


@dataclass(frozen=True)
class ImplContext:
    project_id: str
    impl_node_id: str
    owner_id: str
    owner_name: str
    context_kwargs: dict[str, Any]


def gather_impl_context(db: Session, project_id: str, impl_node_id: str) -> ImplContext:
    impl_node = db.get(Node, impl_node_id)
    if impl_node is None or impl_node.project_id != project_id:
        raise ValueError(f"Impl node {impl_node_id!r} not found in project {project_id!r}")
    if impl_node.tier != "impl" or impl_node.parent_id is None:
        raise ValueError(
            f"Node {impl_node_id!r} is not an impl with a parent owner "
            f"(tier={impl_node.tier!r}, parent_id={impl_node.parent_id!r})"
        )
    owner = db.get(Node, impl_node.parent_id)
    if owner is None:
        raise ValueError(f"Impl {impl_node_id!r} owner {impl_node.parent_id!r} not found")
    regen_ctx = build_regen_context(db, owner.id)
    context_kwargs = format_regen_context_for_impl(regen_ctx)
    return ImplContext(
        project_id=project_id,
        impl_node_id=impl_node_id,
        owner_id=owner.id,
        owner_name=owner.name,
        context_kwargs=context_kwargs,
    )
