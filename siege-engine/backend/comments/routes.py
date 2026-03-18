import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.models import Artifact, ArtifactComment, User
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateCommentRequest(BaseModel):
    content: str
    parent_id: str | None = None


def _comment_to_dict(comment: ArtifactComment, db: Session) -> dict:
    author = db.get(User, comment.author_id) if comment.author_id else None
    return {
        "id": comment.id,
        "artifact_id": comment.artifact_id,
        "project_id": comment.project_id,
        "author": {
            "id": author.id,
            "username": author.username,
        }
        if author
        else None,
        "content": comment.content,
        "comment_type": comment.comment_type,
        "parent_id": comment.parent_id,
        "artifact_version": comment.artifact_version,
        "created_at": comment.created_at.isoformat(),
    }


@router.get("/{project_id}/artifacts/{artifact_id}/comments")
def list_comments(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    comments = (
        db.query(ArtifactComment)
        .filter_by(project_id=project_id, artifact_id=artifact_id)
        .order_by(ArtifactComment.created_at.asc())
        .all()
    )
    return [_comment_to_dict(c, db) for c in comments]


@router.post("/{project_id}/artifacts/{artifact_id}/comments")
def create_comment(
    project_id: str,
    artifact_id: str,
    req: CreateCommentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # Viewers CAN comment
):
    if not req.content.strip():
        raise HTTPException(400, "Comment content cannot be empty")

    # Enforce shallow threading: parent must be a top-level comment
    if req.parent_id:
        parent = db.get(ArtifactComment, req.parent_id)
        if not parent:
            raise HTTPException(404, "Parent comment not found")
        if parent.parent_id is not None:
            raise HTTPException(400, "Cannot reply to a reply (shallow threading only)")

    # Get current artifact version for context
    artifact = db.query(Artifact).filter_by(id=artifact_id).first()
    version = artifact.version if artifact else None

    comment = ArtifactComment(
        artifact_id=artifact_id,
        project_id=project_id,
        author_id=user.id,
        content=req.content.strip(),
        comment_type="comment",
        parent_id=req.parent_id,
        artifact_version=version,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Broadcast to connected clients
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(
            ws_manager.broadcast(
                project_id,
                {
                    "type": "comment_added",
                    "artifact_id": artifact_id,
                    "comment_id": comment.id,
                },
            )
        )
    except RuntimeError:
        pass  # No event loop running (e.g. in tests)

    return _comment_to_dict(comment, db)
