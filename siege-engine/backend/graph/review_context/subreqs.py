"""Shared context builder for the subreqs tier.

Both :mod:`backend.graph.handlers.subreqs_generation` (the
generator) and :mod:`backend.graph.handlers.review_subreqs` (the
Phase 8 reviewer) call :func:`gather_subreqs_context` to produce
the exact same input bundle. That guarantees the reviewer is
critiquing the model against what the generator actually saw —
no context drift.

The returned dataclass carries every prompt-ready string plus
the auxiliary fields the validator or handler needs downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.prompts.subrequirements import (
    format_component_summary,
    format_domain_parent_context,
    format_parent_resps_summary,
    format_sibling_dep_context,
)
from backend.graph.queries import (
    dependencies_of,
    domain_parents_of,
    list_subresponsibilities,
    top_level_resps_assigned_to,
)
from backend.graph.references import render_referenced_content_summary
from backend.graph.subrequirements import get_subreqs_node, pending_subreqs_draft
from backend.graph.vocabulary import render_vocab_summary_for_node
from backend.models.node import Draft, Fragment, Node


@dataclass(frozen=True)
class SubreqsContext:
    """Everything the subreqs prompt renders or the validator needs.

    Shared between the generator and the reviewer. ``prior_pending``
    is the current pending draft's content (if any) — useful for
    the generator's retry framing; the reviewer ignores it since
    the review always targets the draft that just committed.
    """

    project_id: str
    component_id: str
    component_name: str
    component_kind: str  # "domain" | "presentational"
    subreqs_node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    component_summary: str
    parent_resps_summary: str
    known_parent_resp_ids: set[str]
    domain_parent_context: str | None
    sibling_dep_context: str | None
    vocab_summary: str
    referenced_content_summary: str


def gather_subreqs_context(db: Session, project_id: str, component_id: str) -> SubreqsContext:
    """Build the subreqs prompt context from DB state.

    Raises ``ValueError`` if the component is missing, belongs to
    a different project, or is not on the ``comp`` tier, or if its
    bootstrapped subreqs node is missing. Matches the generator's
    precondition checks so the reviewer can't run on state the
    generator would have rejected.
    """
    comp_node = db.get(Node, component_id)
    if comp_node is None or comp_node.project_id != project_id:
        raise ValueError(f"Component {component_id!r} not found in project {project_id!r}")
    if comp_node.tier != "comp":
        raise ValueError(f"Node {component_id!r} is not a comp_* node (tier={comp_node.tier!r})")

    subreqs_node = get_subreqs_node(db, project_id, component_id)
    if subreqs_node is None:
        raise ValueError(
            f"Component {component_id!r} has no subreqs node; "
            "was bootstrap_subreqs_node called at mint_sysarch time?"
        )

    prior_approved: str | None = subreqs_node.content or None
    pending: Draft | None = pending_subreqs_draft(db, project_id, component_id)
    prior_pending: str | None = pending.content if pending else None
    prior_pending_id: str | None = pending.id if pending else None

    role = _read_fragment(db, component_id, FragmentKind.TECHSPEC) or ""
    api_intent = _read_fragment(db, component_id, FragmentKind.PUBAPI) or ""
    component_summary = format_component_summary(
        name=comp_node.name, role=role, api_intent=api_intent
    )

    parent_resp_rows = top_level_resps_assigned_to(db, component_id)
    parent_resps_summary = format_parent_resps_summary(
        [{"id": r.id, "name": r.name, "content": r.content} for r in parent_resp_rows]
    )
    known_parent_resp_ids: set[str] = {r.id for r in parent_resp_rows}

    domain_parent_context: str | None = None
    if comp_node.kind == "presentational":
        parent_bundles: list[dict] = []
        for parent in domain_parents_of(db, component_id):
            parent_subresps = list_subresponsibilities(db, parent.id)
            parent_bundles.append(
                {
                    "name": parent.name,
                    "subresps": [
                        {"id": sr.id, "name": sr.name, "content": sr.content}
                        for sr in parent_subresps
                    ],
                }
            )
        rendered = format_domain_parent_context(parent_bundles)
        domain_parent_context = rendered or None

    sibling_dep_context: str | None = None
    dep_rows = dependencies_of(db, component_id)
    if dep_rows:
        dep_bundles: list[dict] = []
        for dep in dep_rows:
            dep_pubapi = _read_fragment(db, dep.id, FragmentKind.PUBAPI) or ""
            dep_resps = top_level_resps_assigned_to(db, dep.id)
            dep_bundles.append(
                {
                    "name": dep.name,
                    "api_intent": dep_pubapi,
                    "responsibilities": [
                        {"id": r.id, "name": r.name, "content": r.content} for r in dep_resps
                    ],
                }
            )
        rendered_deps = format_sibling_dep_context(dep_bundles)
        sibling_dep_context = rendered_deps or None

    vocab_summary = render_vocab_summary_for_node(db, project_id, component_id)
    referenced_content_summary = render_referenced_content_summary(db, project_id, subreqs_node.id)

    return SubreqsContext(
        project_id=project_id,
        component_id=component_id,
        component_name=comp_node.name,
        component_kind=comp_node.kind,
        subreqs_node_id=subreqs_node.id,
        prior_approved=prior_approved,
        prior_pending=prior_pending,
        prior_pending_id=prior_pending_id,
        component_summary=component_summary,
        parent_resps_summary=parent_resps_summary,
        known_parent_resp_ids=known_parent_resp_ids,
        domain_parent_context=domain_parent_context,
        sibling_dep_context=sibling_dep_context,
        vocab_summary=vocab_summary,
        referenced_content_summary=referenced_content_summary,
    )


def _read_fragment(db: Session, owner_id: str, kind: FragmentKind) -> str | None:
    fid = fragment_id(owner_id, kind)
    frag = db.get(Fragment, fid)
    return frag.content if frag is not None else None
