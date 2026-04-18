"""Review-side context for feature expansion.

Mirrors the generator's context at
``backend.graph.handlers.feature_expansion`` lines ~115-145.
Keep in sync if the generator's inputs change.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.graph.expansion import get_expansion_node
from backend.models import InputDocument


@dataclass(frozen=True)
class ExpansionContext:
    project_id: str
    node_id: str
    input_doc: str


def gather_expansion_context(db: Session, project_id: str, node_id: str) -> ExpansionContext:
    node = get_expansion_node(db, project_id)
    if node is None or node.id != node_id:
        raise ValueError(f"Expansion node {node_id!r} not found in project {project_id!r}")
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
    return ExpansionContext(project_id=project_id, node_id=node.id, input_doc=input_doc)
