from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.dag import service as dag_service
from backend.database import get_db
from backend.models import ComponentDefinition, Project, User

router = APIRouter()


@router.get("/{project_id}")
def get_dag(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return dag_service.get_dag_visualization_data(db, project_id)


@router.get("/{project_id}/documents")
def get_documents_dag(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return dag_service.get_documents_dag(db, project_id)


@router.get("/{project_id}/components")
def get_components(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    comps = (
        db.query(ComponentDefinition)
        .filter_by(project_id=project_id)
        .filter(ComponentDefinition.parent_key.is_(None))
        .all()
    )

    # Build dependents map (reverse of dependencies)
    dependents: dict[str, list[str]] = {}
    for comp in comps:
        for dep_key in (comp.dependencies or []):
            dependents.setdefault(dep_key, []).append(comp.key)

    return [
        {
            "key": c.key,
            "name": c.name,
            "description": c.description,
            "dependencies": c.dependencies or [],
            "dependents": dependents.get(c.key, []),
        }
        for c in comps
    ]


@router.get("/{project_id}/stale")
def get_stale(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {"stale_artifact_ids": dag_service.get_stale_artifacts(db, project_id)}


@router.post("/{project_id}/propagate/{artifact_id}")
def propagate(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stale_ids = dag_service.propagate_staleness(db, artifact_id)
    db.commit()
    return {"stale_ids": stale_ids}
