"""HTTP routes for v3 git-backed references.

The legacy ``POST /api/projects/<id>/references/create`` endpoint
stays alive for the dashboard's existing seed-expansion flow. This
module adds the v3 alternative:

- ``POST /api/projects/<id>/references`` — register a ref whose
  body lives in the project repo at ``refs/<ref_id>/body.md``.
  The caller has already committed + pushed; the request payload
  carries ``{ref_id, name, body_sha, body_path}`` and the server
  records the ref node + git coordinates without calling the LLM.
- ``GET /api/projects/<id>/references/by-name?name=...`` — name
  lookup so the CLI can avoid creating a duplicate ref by name.

Reading body content: ``resolve_ref_body`` (below) prefers git
when ``body_sha`` is set, falls back to ``Node.content`` on git
failure or for legacy rows.
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


# ── Request / response models ────────────────────────────────────────


class CreateGitReferenceRequest(BaseModel):
    """Register a git-resident reference.

    ``ref_id`` is minted by the CLI before the body file is written
    so the file path can include the id. The server accepts the
    caller's minted id provided it's well-formed and not already
    taken.
    """

    ref_id: str
    name: str
    body_sha: str
    body_path: str | None = None


class GitReferenceResponse(BaseModel):
    id: str
    project_id: str
    name: str
    body_sha: str | None
    body_path: str | None
    created_at: str
    updated_at: str


def _serialize_ref(node: Node) -> GitReferenceResponse:
    return GitReferenceResponse(
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


# Caller-supplied ref ids must match the platform's id grammar
# (``ref_`` prefix + Crockford base32). siege.graph.ids.mint
# produces these; the CLI mints locally and passes through.
_REF_ID_RE = re.compile(r"^ref_[0-9A-HJKMNP-TV-Z]{8,}$")


# ── Endpoints ────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/references",
    response_model=GitReferenceResponse,
)
def post_create_git_reference(
    project_id: str,
    req: CreateGitReferenceRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GitReferenceResponse:
    """Register a v3 git-backed reference node.

    The caller (typically Claude Code via ``siege.cli create-ref``)
    has already minted the ref id locally, written the body to
    ``refs/<ref_id>/body.md`` in the project repo, and pushed the
    commit. This endpoint records the ref node + git coordinates.
    The server does NOT call the LLM — body content is whatever
    the caller wrote.
    """
    _require_project(db, project_id)

    ref_id = req.ref_id.strip()
    if not _REF_ID_RE.match(ref_id):
        raise HTTPException(
            status_code=422,
            detail=f"ref_id must match ref_<Crockford-base32>; got {ref_id!r}",
        )
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name cannot be empty")
    body_sha = req.body_sha.strip()
    if not body_sha:
        raise HTTPException(status_code=422, detail="body_sha cannot be empty")

    body_path = (req.body_path or f"refs/{ref_id}/body.md").strip()

    # Refuse duplicate ref_id within the project.
    existing = db.get(Node, ref_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Reference {ref_id} already exists in this project.",
        )

    # Refuse duplicate name within the project's ref pool.
    from backend.graph.references import reference_by_name

    by_name = reference_by_name(db, project_id, name)
    if by_name is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Reference named {name!r} already exists in this project.",
        )

    # Mint via the reducer so the node + creation event are captured.
    # Sentinel ``content`` keeps the NOT NULL constraint satisfied;
    # the real body is read from git on demand.
    sentinel = f"<git-resident: ref sha={body_sha[:12]}>"
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=ref_id,
            tier="ref",
            kind="domain",
            parent_id=None,
            name=name,
            content=sentinel,
        ),
    )
    # Set body_sha + body_path post-mint — the NodeCreated event's
    # current shape doesn't carry these fields; we patch the row in
    # the same transaction the reducer just opened.
    node = db.get(Node, ref_id)
    if node is None:  # pragma: no cover - reducer just created it
        raise HTTPException(status_code=500, detail="ref node disappeared after mint")
    node.body_sha = body_sha
    node.body_path = body_path
    node.updated_at = datetime.utcnow()

    commit_and_publish(db, project_id)
    db.refresh(node)

    logger.info(
        "v3 reference registered project=%s ref_id=%s name=%s sha=%s",
        project_id,
        ref_id,
        name,
        body_sha[:12],
    )
    return _serialize_ref(node)


@router.get(
    "/{project_id}/references/by-name",
    response_model=GitReferenceResponse | None,  # type: ignore[arg-type]
)
def get_reference_by_name(
    project_id: str,
    name: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GitReferenceResponse | None:
    """Look up a ref by name within a project.

    Returns the ref's row if it exists, ``null`` if not. The CLI
    uses this for pre-create idempotency — "does a ref named X
    already exist?" — without having to fetch the full list.
    """
    _require_project(db, project_id)
    from backend.graph.references import reference_by_name

    node = reference_by_name(db, project_id, name)
    if node is None:
        return None
    return _serialize_ref(node)


# ── Body resolution helper ───────────────────────────────────────────


def resolve_ref_body(node: Node) -> str:
    """Return a ref node's body text.

    v3 refs store the body in git at ``body_path``; legacy refs
    store it inline in ``content``. Prefer the git path when
    ``body_sha`` is set; fall back to ``content`` on git fetch
    failure so the handler stays resilient through transient git
    issues.
    """
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
            "Failed to fetch v3 ref body via git for project=%s ref=%s "
            "path=%s: %s — falling back to content column",
            node.project_id,
            node.id,
            node.body_path,
            exc,
        )
        return node.content or ""


__all__ = ["router", "resolve_ref_body"]
