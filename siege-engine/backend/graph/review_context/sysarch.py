"""Review-side context for the sysarch tier."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.graph.prompts.requirements import format_features_summary
from backend.graph.prompts.sysarch import format_reqs_summary
from backend.graph.references import render_referenced_content_summary
from backend.graph.sysarch import get_sysarch_node
from backend.graph.vocabulary import render_vocab_summary_all
from backend.models import InputDocument
from backend.models.node import Node


@dataclass(frozen=True)
class SysarchContext:
    project_id: str
    node_id: str
    features_summary: str
    reqs_summary: str
    vocab_summary: str
    referenced_content_summary: str
    input_doc: str


def gather_sysarch_context(db: Session, project_id: str, node_id: str) -> SysarchContext:
    sysarch_node = get_sysarch_node(db, project_id)
    if sysarch_node is None or sysarch_node.id != node_id:
        raise ValueError(f"Sysarch node {node_id!r} not found in project {project_id!r}")
    feature_rows = (
        db.query(Node)
        .filter(Node.project_id == project_id, Node.tier == "feat")
        .order_by(Node.display_order, Node.created_at)
        .all()
    )
    features_summary = format_features_summary(
        [
            {
                "id": f.id,
                "name": f.name,
                "content": f.content,
                "group_label": f.group_label,
                "is_implicit": f.is_implicit,
            }
            for f in feature_rows
        ]
    )
    resp_rows = (
        db.query(Node)
        .filter(
            Node.project_id == project_id,
            Node.tier == "resp",
            Node.parent_id.is_(None),
        )
        .order_by(Node.display_order, Node.created_at)
        .all()
    )
    reqs_summary = format_reqs_summary(
        [
            {
                "id": r.id,
                "name": r.name,
                "content": r.content,
                "is_implicit": r.is_implicit,
            }
            for r in resp_rows
        ]
    )
    vocab_summary = render_vocab_summary_all(db, project_id)
    referenced_content_summary = render_referenced_content_summary(db, project_id, sysarch_node.id)
    input_doc_row = (
        db.query(InputDocument)
        .filter(
            InputDocument.project_id == project_id,
            InputDocument.doc_type == "project_doc",
        )
        .order_by(InputDocument.created_at.desc())
        .first()
    )
    input_doc = input_doc_row.content if input_doc_row else ""
    return SysarchContext(
        project_id=project_id,
        node_id=sysarch_node.id,
        features_summary=features_summary,
        reqs_summary=reqs_summary,
        vocab_summary=vocab_summary,
        referenced_content_summary=referenced_content_summary,
        input_doc=input_doc,
    )
