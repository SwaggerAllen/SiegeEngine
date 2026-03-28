"""CRUD routes for input documents."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer, get_current_user
from backend.database import get_db
from backend.models import (
    Artifact,
    ArtifactStatus,
    InputDocument,
    Project,
    User,
)
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

input_docs_router = APIRouter()


class InputDocCreate(BaseModel):
    name: str
    content: str
    doc_type: str = "reference"
    inject_into_stages: list[str] = ["system_architecture", "extract_components", "component_architectures"]


class InputDocUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    doc_type: str | None = None
    inject_into_stages: list[str] | None = None


class InputDocResponse(BaseModel):
    id: str
    name: str
    content: str
    doc_type: str
    inject_into_stages: list[str]
    version: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@input_docs_router.get("/{project_id}/input-docs")
def list_input_docs(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_project_or_404(db, project_id)
    docs = db.query(InputDocument).filter_by(project_id=project_id).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "content": d.content,
            "doc_type": d.doc_type,
            "inject_into_stages": d.inject_into_stages,
            "version": d.version,
            "created_at": d.created_at.isoformat(),
            "updated_at": d.updated_at.isoformat(),
        }
        for d in docs
    ]


@input_docs_router.post("/{project_id}/input-docs")
async def create_input_doc(
    project_id: str,
    req: InputDocCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    _get_project_or_404(db, project_id)

    doc = InputDocument(
        project_id=project_id,
        name=req.name,
        content=req.content,
        doc_type=req.doc_type,
        inject_into_stages=req.inject_into_stages,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Mark system_requirements as stale so changes propagate on next run
    _mark_root_stale(db, project_id)

    await ws_manager.broadcast(
        project_id,
        {"type": "input_doc_changed", "action": "created", "doc_id": doc.id},
    )

    return {
        "id": doc.id,
        "name": doc.name,
        "version": doc.version,
    }


@input_docs_router.put("/{project_id}/input-docs/{doc_id}")
async def update_input_doc(
    project_id: str,
    doc_id: str,
    req: InputDocUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    doc = db.get(InputDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(404, "Input document not found")

    content_changed = False
    if req.name is not None:
        doc.name = req.name
    if req.content is not None and req.content != doc.content:
        doc.content = req.content
        doc.version += 1
        content_changed = True
    if req.doc_type is not None:
        doc.doc_type = req.doc_type
    if req.inject_into_stages is not None:
        doc.inject_into_stages = req.inject_into_stages

    db.commit()

    if content_changed:
        # Mark downstream artifacts as stale
        _mark_root_stale(db, project_id)

        await ws_manager.broadcast(
            project_id,
            {"type": "input_doc_changed", "action": "updated", "doc_id": doc_id},
        )

    return {
        "id": doc.id,
        "name": doc.name,
        "version": doc.version,
    }


@input_docs_router.delete("/{project_id}/input-docs/{doc_id}")
async def delete_input_doc(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    doc = db.get(InputDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(404, "Input document not found")

    db.delete(doc)
    db.commit()

    _mark_root_stale(db, project_id)

    await ws_manager.broadcast(
        project_id,
        {"type": "input_doc_changed", "action": "deleted", "doc_id": doc_id},
    )

    return {"status": "deleted"}


def _mark_root_stale(db: Session, project_id: str):
    """Mark system_architecture artifact as stale to trigger propagation."""
    from backend.dag.service import propagate_staleness

    sys_arch = (
        db.query(Artifact)
        .filter_by(
            project_id=project_id,
            artifact_type="system_architecture",
            status=ArtifactStatus.APPROVED,
        )
        .first()
    )
    if sys_arch:
        from backend.pipeline.event_store import EventStore

        stale_ids = propagate_staleness(db, sys_arch.id, event_store=EventStore(db))
        logger.info(
            "Input doc change: marked %d artifacts stale (including system_architecture)",
            len(stale_ids) + 1,
        )
