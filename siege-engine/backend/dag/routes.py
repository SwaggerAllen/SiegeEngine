from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.dag import service as dag_service
from backend.database import get_db
from backend.models import Artifact, ArtifactType, ComponentDefinition, Project, User
from backend.pipeline.nodes.extract_components import (
    parse_components_from_content,
    parse_dual_components_from_content,
)

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
    dag_type: str = Query("domain"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if dag_type not in ("domain", "frontend"):
        raise HTTPException(400, "dag_type must be 'domain' or 'frontend'")
    try:
        return dag_service.get_documents_dag(db, project_id, dag_type=dag_type)
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/{project_id}/components")
def get_components(
    project_id: str,
    parent_key: Optional[str] = Query(None),
    dag_type: str = Query("domain"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    is_frontend = dag_type == "frontend"

    # Determine whether we're listing top-level components or sub-components
    if parent_key:
        artifact_type = (
            ArtifactType.FRONTEND_SUB_COMPONENT_MAP
            if is_frontend
            else ArtifactType.SUB_COMPONENT_MAP
        )
        comp_defs = (
            db.query(ComponentDefinition)
            .filter_by(
                project_id=project_id,
                parent_key=parent_key,
                dag_type=dag_type,
            )
            .all()
        )
    else:
        # Top-level component_map is the shared extraction artifact
        artifact_type = ArtifactType.COMPONENT_MAP
        comp_defs = (
            db.query(ComponentDefinition)
            .filter_by(project_id=project_id, dag_type=dag_type)
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
        if is_frontend and not parent_key:
            dual = parse_dual_components_from_content(artifact.content)
            parsed = dual["frontend"]
            # Auto-split: move domain keys from dependencies → domain_parents
            domain_keys = {c["key"] for c in dual["domain"]}
            fe_keys = {c["key"] for c in parsed}
            for comp in parsed:
                raw_deps = comp.get("dependencies") or []
                explicit_parents = comp.get("domain_parents") or []
                intra_deps = []
                cross_parents = list(explicit_parents)
                for dep in raw_deps:
                    if dep in fe_keys:
                        intra_deps.append(dep)
                    elif dep in domain_keys:
                        if dep not in cross_parents:
                            cross_parents.append(dep)
                    else:
                        intra_deps.append(dep)
                comp["dependencies"] = intra_deps
                comp["domain_parents"] = cross_parents
        else:
            parsed = parse_components_from_content(artifact.content)
    else:
        parsed = []

    if is_reviewing and existing_by_key:
        parsed_keys = {c["key"] for c in parsed}
        existing_keys = set(existing_by_key.keys())

        components = []
        for c in parsed:
            components.append(
                {
                    "key": c["key"],
                    "name": c.get("name", c["key"]),
                    "description": c.get("description"),
                    "dependencies": c.get("dependencies") or [],
                    "domain_parents": c.get("domain_parents") or [],
                    "change": "existing" if c["key"] in existing_keys else "new",
                }
            )
        for key, cd in existing_by_key.items():
            if key not in parsed_keys:
                components.append(
                    {
                        "key": cd.key,
                        "name": cd.name,
                        "description": cd.description,
                        "dependencies": cd.dependencies or [],
                        "domain_parents": cd.domain_parents or [],
                        "change": "removed",
                    }
                )
    elif existing_by_key:
        components = [
            {
                "key": c.key,
                "name": c.name,
                "description": c.description,
                "dependencies": c.dependencies or [],
                "domain_parents": c.domain_parents or [],
                "change": None,
            }
            for c in comp_defs
        ]
    elif parsed:
        components = [
            {
                "key": c["key"],
                "name": c.get("name", c["key"]),
                "description": c.get("description"),
                "dependencies": c.get("dependencies") or [],
                "domain_parents": c.get("domain_parents") or [],
                "change": "new",
            }
            for c in parsed
        ]
    else:
        return []

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
            "domain_parents": c.get("domain_parents") or [],
            "change": c.get("change"),
        }
        for c in components
    ]


@router.get("/{project_id}/cross-dag-status")
def get_cross_dag_status(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return cross-DAG relationships for frontend/domain components."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    from backend.pipeline.event_store import EventStore

    snapshot = EventStore(db).get_snapshot(project_id)
    stage_statuses = snapshot.stage_statuses or {}

    fe_comps = (
        db.query(ComponentDefinition)
        .filter_by(project_id=project_id, dag_type="frontend")
        .filter(ComponentDefinition.parent_key.is_(None))
        .all()
    )

    result = []
    for fc in fe_comps:
        parents = []
        for dp_key in fc.domain_parents or []:
            status_key = f"component_architectures/{dp_key}"
            parents.append(
                {
                    "key": dp_key,
                    "architecture_status": stage_statuses.get(status_key, "pending"),
                }
            )
        result.append(
            {
                "frontend_component": fc.key,
                "frontend_component_name": fc.name,
                "domain_parents": parents,
            }
        )

    return result


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
