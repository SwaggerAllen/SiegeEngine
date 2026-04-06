from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.dag import service as dag_service
from backend.database import get_db
from backend.models import Artifact, ArtifactType, ComponentDefinition, Project, User
from backend.pipeline.nodes.extract_components import parse_components_from_content

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
    try:
        return dag_service.get_dag_visualization_data(db, project_id)
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/{project_id}/documents")
def get_documents_dag(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        return dag_service.get_documents_dag(db, project_id)
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/{project_id}/components")
def get_components(
    project_id: str,
    parent_key: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Determine whether we're listing top-level components or sub-components
    if parent_key:
        artifact_type = ArtifactType.SUB_COMPONENT_MAP
        comp_defs = (
            db.query(ComponentDefinition)
            .filter_by(project_id=project_id, parent_key=parent_key)
            .all()
        )
    else:
        artifact_type = ArtifactType.COMPONENT_MAP
        comp_defs = (
            db.query(ComponentDefinition)
            .filter_by(project_id=project_id)
            .filter(ComponentDefinition.parent_key.is_(None))
            .all()
        )
    existing_by_key = {c.key: c for c in comp_defs}

    # Try to parse the latest component/sub-component map artifact
    q = db.query(Artifact).filter_by(project_id=project_id, artifact_type=artifact_type)
    if parent_key:
        q = q.filter_by(component_key=parent_key)
    artifact = q.first()

    # Read status from snapshot (source of truth)
    from backend.pipeline.event_store import EventStore

    snapshot = EventStore(db).get_snapshot(project_id)
    artifact_status = (snapshot.artifact_statuses or {}).get(artifact.id) if artifact else None
    is_reviewing = artifact_status in (
        "awaiting_review",
        "generating",
        "ai_reviewing",
    )

    if artifact and artifact.content:
        parsed = parse_components_from_content(artifact.content)
    else:
        parsed = []

    if is_reviewing and existing_by_key:
        # Merge: show new components from artifact + existing DB components
        # so reviewer can see the full picture and spot duplicates
        parsed_keys = {c["key"] for c in parsed}
        existing_keys = set(existing_by_key.keys())

        components = []
        # Components in the new extraction
        for c in parsed:
            components.append(
                {
                    "key": c["key"],
                    "name": c.get("name", c["key"]),
                    "description": c.get("description"),
                    "dependencies": c.get("dependencies") or [],
                    "change": "existing" if c["key"] in existing_keys else "new",
                }
            )
        # Components in the old set that are NOT in the new extraction
        for key, cd in existing_by_key.items():
            if key not in parsed_keys:
                components.append(
                    {
                        "key": cd.key,
                        "name": cd.name,
                        "description": cd.description,
                        "dependencies": cd.dependencies or [],
                        "change": "removed",
                    }
                )
    elif existing_by_key:
        # Not reviewing — just show DB records
        components = [
            {
                "key": c.key,
                "name": c.name,
                "description": c.description,
                "dependencies": c.dependencies or [],
                "change": None,
            }
            for c in comp_defs
        ]
    elif parsed:
        # First extraction, no existing DB records
        components = [
            {
                "key": c["key"],
                "name": c.get("name", c["key"]),
                "description": c.get("description"),
                "dependencies": c.get("dependencies") or [],
                "change": "new",
            }
            for c in parsed
        ]
    else:
        return []

    # Build dependents map (reverse of dependencies) across all components
    dependents: dict[str, list[str]] = {}
    for comp in components:
        for dep_key in comp.get("dependencies") or []:
            dependents.setdefault(dep_key, []).append(comp["key"])

    return [
        {
            "key": c["key"],
            "name": c.get("name", c["key"]),
            "description": c.get("description"),
            "dependencies": c.get("dependencies") or [],
            "dependents": dependents.get(c["key"], []),
            "change": c.get("change"),
        }
        for c in components
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
    from backend.pipeline.event_store import EventStore

    stale_ids = dag_service.propagate_staleness(db, artifact_id, event_store=EventStore(db))
    db.commit()
    return {"stale_ids": stale_ids}
