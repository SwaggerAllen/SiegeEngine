"""Review-side context for the comparch tier.

Reuses the generator's ``build_regen_context`` / ``format_regen_context``
pipeline directly — zero drift. Adds one extra section the
generator already has via per-comp inheritance: the project's
sysarch techspec, dumped explicitly so the reviewer's
"flag drift from the project techspec" check has a concrete
baseline to compare the comparch against (without it, the LLM
hallucinates a default tech stack).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.regen_context import build_regen_context, format_regen_context
from backend.models.node import Fragment, Node


@dataclass(frozen=True)
class ComparchContext:
    project_id: str
    component_id: str
    component_name: str
    component_kind: str
    target_is_foundation: bool
    context_kwargs: dict[str, Any]  # the rendered context bundle


def _load_project_techspec(db: Session, project_id: str) -> str:
    """Return the project's sysarch-tier techspec fragment content.

    Empty string if the sysarch node hasn't been minted yet (so
    the reviewer still gets a context bundle, just without the
    tech-stack baseline).
    """
    sysarch_node = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "sysarch",
        )
    ).scalar_one_or_none()
    if sysarch_node is None:
        return ""
    frag = db.get(Fragment, fragment_id(sysarch_node.id, FragmentKind.TECHSPEC))
    if frag is None:
        return ""
    return (frag.content or "").strip()


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
    project_techspec = _load_project_techspec(db, project_id)
    if project_techspec:
        context_kwargs = {"project_techspec": project_techspec, **context_kwargs}
    return ComparchContext(
        project_id=project_id,
        component_id=component_id,
        component_name=comp_node.name,
        component_kind=comp_node.kind,
        target_is_foundation=bool(comp_node.is_foundation),
        context_kwargs=context_kwargs,
    )
