"""HTTP routes for v3 git-backed vocabulary entries.

Same shape as ``references_git_routes`` — vocab entries move to
"body in git, state in Postgres" the same way refs did. The
legacy vocab CRUD endpoints in ``routes.py`` stay alive during
the migration but are retired in a follow-up sweep.

- ``POST /api/projects/<id>/vocabulary`` — register a v3 vocab
  entry whose body lives at ``vocab/<vocab_id>/body.md``.
- ``GET /api/projects/<id>/vocabulary/by-name`` — name lookup.

Body content reads via ``resolve_vocab_body`` (below) prefer git
when ``body_sha`` is set, fall back to ``Node.content`` for
legacy rows or git failure.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.reducer import append_event
from backend.models import Project, User
from backend.models.node import Node

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateGitVocabRequest(BaseModel):
    vocab_id: str
    name: str
    body_sha: str
    body_path: str | None = None


class GitVocabResponse(BaseModel):
    id: str
    project_id: str
    name: str
    body_sha: str | None
    body_path: str | None
    created_at: str
    updated_at: str


def _serialize_vocab(node: Node) -> GitVocabResponse:
    return GitVocabResponse(
        id=node.id,
        project_id=node.project_id,
        name=node.name,
        body_sha=node.body_sha,
        body_path=node.body_path,
        created_at=node.created_at.isoformat() if node.created_at else "",
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


_VOCAB_ID_RE = re.compile(r"^vocab_[0-9A-HJKMNP-TV-Z]{8,}$")


def _vocab_by_name(db: Session, project_id: str, name: str) -> Node | None:
    return (
        db.query(Node)
        .filter(
            Node.project_id == project_id,
            Node.tier == "vocab",
            Node.name == name.strip(),
        )
        .first()
    )


@router.post(
    "/{project_id}/vocabulary",
    response_model=GitVocabResponse,
)
def post_create_git_vocab(
    project_id: str,
    req: CreateGitVocabRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GitVocabResponse:
    """Register a v3 git-backed vocab entry.

    Caller (typically ``siege.cli create-vocab``) has minted the
    vocab id locally, written the body to ``vocab/<vocab_id>/body.md``,
    and pushed. This endpoint records the node + git coordinates.
    No LLM call.
    """
    _require_project(db, project_id)

    vocab_id = req.vocab_id.strip()
    if not _VOCAB_ID_RE.match(vocab_id):
        raise HTTPException(
            status_code=422,
            detail=f"vocab_id must match vocab_<Crockford-base32>; got {vocab_id!r}",
        )
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name cannot be empty")
    body_sha = req.body_sha.strip()
    if not body_sha:
        raise HTTPException(status_code=422, detail="body_sha cannot be empty")

    body_path = (req.body_path or f"vocab/{vocab_id}/body.md").strip()

    if db.get(Node, vocab_id) is not None:
        raise HTTPException(status_code=409, detail=f"Vocab {vocab_id} already exists.")
    if _vocab_by_name(db, project_id, name) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Vocab named {name!r} already exists in this project.",
        )

    sentinel = f"<git-resident: vocab sha={body_sha[:12]}>"
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=vocab_id,
            tier="vocab",
            kind="domain",
            parent_id=None,
            name=name,
            content=sentinel,
        ),
    )
    node = db.get(Node, vocab_id)
    if node is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="vocab node disappeared after mint")
    node.body_sha = body_sha
    node.body_path = body_path
    node.updated_at = datetime.utcnow()

    commit_and_publish(db, project_id)
    db.refresh(node)

    logger.info(
        "v3 vocab registered project=%s vocab_id=%s name=%s sha=%s",
        project_id,
        vocab_id,
        name,
        body_sha[:12],
    )
    return _serialize_vocab(node)


@router.get(
    "/{project_id}/vocabulary/by-name",
    response_model=GitVocabResponse | None,  # type: ignore[arg-type]
)
def get_vocab_by_name(
    project_id: str,
    name: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GitVocabResponse | None:
    _require_project(db, project_id)
    node = _vocab_by_name(db, project_id, name)
    if node is None:
        return None
    return _serialize_vocab(node)


def resolve_vocab_body(node: Node) -> str:
    """Return a vocab node's body text — git for v3 rows, content
    column for legacy or on git failure."""
    if not node.body_sha or not node.body_path:
        return node.content or ""
    try:
        from siege.auth_lookup import lookup_project_auth
        from siege.git_view import cache as view_cache

        auth = lookup_project_auth(node.project_id, None)
        view = view_cache.get_view(
            node.project_id,
            "main",
            remote_url=auth.remote_url,
            access_token=auth.access_token,
        )
        return view.read_body_text(node.body_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to fetch v3 vocab body via git for project=%s vocab=%s "
            "path=%s: %s — falling back to content column",
            node.project_id,
            node.id,
            node.body_path,
            exc,
        )
        return node.content or ""


__all__ = ["router", "resolve_vocab_body"]
