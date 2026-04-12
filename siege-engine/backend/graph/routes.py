"""Debug endpoint for the v2 structured model.

Only one endpoint: ``GET /api/projects/{id}/model`` returns a
projection snapshot. Exists for smoke testing during development and
to back ``tests/v2/test_debug_route.py``. Not intended for production
UI use — later phases will add real, paginated read endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import queries
from backend.models import Project, User

router = APIRouter()


@router.get("/{project_id}/model")
def get_project_model(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return queries.projection_snapshot(db, project_id)
