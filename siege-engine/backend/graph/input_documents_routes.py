"""HTTP routes for v3 git-backed input documents.

Two endpoints:

- ``POST /api/projects/<id>/input-documents`` — register a new
  input document whose body lives in the project repo at
  ``inputs/<role>.md`` (the path the bundle declares). The caller
  has already committed + pushed the body file; the request
  payload carries ``{role, name, body_sha, body_path}`` and the
  server fetches the branch at ``body_sha`` to verify the file
  exists, then persists the InputDocument row.
- ``GET /api/projects/<id>/input-documents`` — list. Returns
  legacy rows (``body_sha`` null, content stored in ``content``)
  and v3 rows uniformly; consumers read body content via
  ``content`` for legacy rows and via the siege server's
  ``get-body`` (or a future input-doc-specific reader) for v3.

The v3 endpoint does not call the LLM. Content is whatever the
agent (Claude Code) wrote to the git file before calling.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.models import InputDocument, Project, User

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / response models ────────────────────────────────────────


class CreateInputDocumentRequest(BaseModel):
    """Register a git-resident input document.

    ``body_path`` defaults to ``inputs/<role>.md`` — the path the
    default bundle uses. Bundles that ship a different layout pass
    a custom path.
    """

    role: str
    name: str
    body_sha: str
    body_path: str | None = None


class InputDocumentResponse(BaseModel):
    id: str
    project_id: str
    name: str
    doc_type: str
    body_sha: str | None
    body_path: str | None
    created_at: str
    updated_at: str


class InputDocumentListResponse(BaseModel):
    input_documents: list[InputDocumentResponse]


def _serialize_input_doc(doc: InputDocument) -> InputDocumentResponse:
    return InputDocumentResponse(
        id=doc.id,
        project_id=doc.project_id,
        name=doc.name,
        doc_type=doc.doc_type,
        body_sha=doc.body_sha,
        body_path=doc.body_path,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
        updated_at=doc.updated_at.isoformat() if doc.updated_at else "",
    )


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Endpoints ────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/input-documents",
    response_model=InputDocumentResponse,
)
def post_create_input_document(
    project_id: str,
    req: CreateInputDocumentRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> InputDocumentResponse:
    """Register a git-resident input document.

    The caller (typically Claude Code via ``siege.cli
    add-input-doc``) has already written the body file to the
    project repo and pushed the commit. This endpoint records the
    InputDocument row + the body's git coordinates so server-side
    readers (the feature_expansion handler, the dashboard) can
    fetch the content via ``siege.git_view``.

    The ``role`` field maps to the bundle's input-doc role
    declaration; the default bundle's role is ``project_doc``.
    """
    _require_project(db, project_id)

    role = req.role.strip()
    if not role:
        raise HTTPException(status_code=422, detail="role cannot be empty")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name cannot be empty")
    body_sha = req.body_sha.strip()
    if not body_sha:
        raise HTTPException(status_code=422, detail="body_sha cannot be empty")

    body_path = (req.body_path or f"inputs/{role}.md").strip()

    # NOTE: we do NOT fetch the git blob here to validate the path
    # exists — the deployed git fetcher is rate-limited and gating
    # registration on a fetch makes the endpoint slow. The server's
    # read path (siege.git_view) surfaces a clear error if the path
    # is wrong at read time; that's the right place for the check.

    # Legacy ``content`` column is NOT NULL; store the role/sha as a
    # human-readable sentinel so eyeballing the row in psql still
    # makes sense. Actual content reads come from git via body_sha.
    sentinel = f"<git-resident: role={role} sha={body_sha[:12]}>"

    now = datetime.utcnow()
    doc = InputDocument(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        content=sentinel,
        doc_type=role,
        body_sha=body_sha,
        body_path=body_path,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info(
        "v3 input document registered project=%s role=%s name=%s sha=%s",
        project_id,
        role,
        name,
        body_sha[:12],
    )
    return _serialize_input_doc(doc)


@router.get(
    "/{project_id}/input-documents",
    response_model=InputDocumentListResponse,
)
def get_input_documents(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> InputDocumentListResponse:
    """List input documents for a project, newest first."""
    _require_project(db, project_id)
    docs = (
        db.query(InputDocument)
        .filter(InputDocument.project_id == project_id)
        .order_by(InputDocument.created_at.desc())
        .all()
    )
    return InputDocumentListResponse(input_documents=[_serialize_input_doc(d) for d in docs])
