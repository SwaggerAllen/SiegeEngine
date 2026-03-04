from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Artifact, ArtifactDependency, ArtifactStatus


def build_dependency_graph(db: Session, project_id: str) -> dict[str, list[str]]:
    deps = db.execute(
        select(ArtifactDependency)
        .join(Artifact, ArtifactDependency.upstream_artifact_id == Artifact.id)
        .where(Artifact.project_id == project_id)
    ).scalars().all()

    graph: dict[str, list[str]] = defaultdict(list)
    for dep in deps:
        graph[dep.upstream_artifact_id].append(dep.downstream_artifact_id)
    return graph


def propagate_staleness(db: Session, artifact_id: str) -> list[str]:
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        return []

    graph = build_dependency_graph(db, artifact.project_id)
    stale_ids: list[str] = []
    queue = deque(graph.get(artifact_id, []))
    visited: set[str] = set()

    while queue:
        current_id = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)

        current = db.get(Artifact, current_id)
        if current and current.status != ArtifactStatus.STALE:
            current.status = ArtifactStatus.STALE
            stale_ids.append(current_id)

        for downstream_id in graph.get(current_id, []):
            queue.append(downstream_id)

    return stale_ids


def get_regeneration_order(
    db: Session, artifact_ids: list[str]
) -> list[list[str]]:
    if not artifact_ids:
        return []

    first = db.get(Artifact, artifact_ids[0])
    if not first:
        return []

    full_graph = build_dependency_graph(db, first.project_id)
    selected = set(artifact_ids)

    in_degree: dict[str, int] = {aid: 0 for aid in selected}
    sub_edges: dict[str, list[str]] = defaultdict(list)

    for upstream_id in selected:
        for downstream_id in full_graph.get(upstream_id, []):
            if downstream_id in selected:
                sub_edges[upstream_id].append(downstream_id)
                in_degree[downstream_id] += 1

    levels: list[list[str]] = []
    queue = [aid for aid, deg in in_degree.items() if deg == 0]

    while queue:
        levels.append(queue)
        next_queue = []
        for aid in queue:
            for downstream in sub_edges.get(aid, []):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    next_queue.append(downstream)
        queue = next_queue

    return levels


def get_stale_artifacts(db: Session, project_id: str) -> list[str]:
    artifacts = db.execute(
        select(Artifact)
        .where(Artifact.project_id == project_id)
        .where(Artifact.status == ArtifactStatus.STALE)
    ).scalars().all()
    return [a.id for a in artifacts]


def get_dag_visualization_data(db: Session, project_id: str) -> dict:
    artifacts = db.execute(
        select(Artifact).where(Artifact.project_id == project_id)
    ).scalars().all()
    deps = db.execute(
        select(ArtifactDependency)
        .join(Artifact, ArtifactDependency.upstream_artifact_id == Artifact.id)
        .where(Artifact.project_id == project_id)
    ).scalars().all()

    nodes = [
        {
            "id": art.id,
            "type": "stageNode",
            "data": {
                "label": art.name,
                "artifact_type": art.artifact_type.value,
                "status": art.status.value,
                "component_key": art.component_key,
                "version": art.version,
            },
            "position": {"x": 0, "y": 0},
        }
        for art in artifacts
    ]

    edges = [
        {
            "id": dep.id,
            "source": dep.upstream_artifact_id,
            "target": dep.downstream_artifact_id,
            "type": "dependencyEdge",
            "animated": True,
        }
        for dep in deps
    ]

    return {"nodes": nodes, "edges": edges}
