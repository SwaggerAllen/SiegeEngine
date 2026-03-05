from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    Artifact,
    ArtifactDependency,
    ArtifactStatus,
    PipelineConfig,
    StageDefinition,
    StageExecution,
    StageStatus,
)


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


def _build_prompt_info(stage_def: StageDefinition) -> dict:
    """Build prompt_info metadata for a DAG node from its stage definition."""
    pc = stage_def.prompt_config
    return {
        "stage_key": stage_def.stage_key,
        "model": pc.model if pc else None,
        "has_custom_config": pc is not None,
        "template_key": stage_def.prompt_template_key,
    }


def get_dag_visualization_data(db: Session, project_id: str) -> dict:
    """Build DAG visualisation from stage definitions (always visible) + artifacts.

    Before the pipeline runs, stage definition placeholder nodes are shown.
    Once artifacts are created, they replace the placeholder for their stage.
    Fan-out stages expand to per-component nodes when artifacts exist.
    """
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        return {"nodes": [], "edges": []}

    stages = sorted(config.stages, key=lambda s: s.order_index)

    # Fetch artifacts and executions
    artifacts = db.execute(
        select(Artifact).where(Artifact.project_id == project_id)
    ).scalars().all()
    executions = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .all()
    )

    # Build lookups
    type_to_artifacts: dict[str, list] = defaultdict(list)
    for art in artifacts:
        type_to_artifacts[art.artifact_type.value].append(art)

    key_to_execs: dict[str, list] = defaultdict(list)
    for exc in executions:
        key_to_execs[exc.stage_key].append(exc)

    nodes: list[dict] = []
    # Map stage_key → list of node IDs produced for that stage
    stage_to_node_ids: dict[str, list[str]] = {}

    for stage_def in stages:
        stage_arts = type_to_artifacts.get(stage_def.output_artifact_type, [])
        stage_execs = key_to_execs.get(stage_def.stage_key, [])

        if len(stage_arts) > 1:
            # Fan-out stage with multiple artifacts — show each component
            node_ids = []
            for art in stage_arts:
                matching_exec = next(
                    (e for e in stage_execs if e.component_key == art.component_key),
                    None,
                )
                is_active = bool(
                    matching_exec
                    and matching_exec.status in (StageStatus.RUNNING, StageStatus.AI_REVIEW)
                )
                nodes.append({
                    "id": art.id,
                    "type": "stageNode",
                    "data": {
                        "label": art.name,
                        "artifact_type": art.artifact_type.value,
                        "status": art.status.value,
                        "component_key": art.component_key,
                        "version": art.version,
                        "stage_key": stage_def.stage_key,
                        "is_active": is_active,
                        "has_artifact": True,
                        "prompt_info": _build_prompt_info(stage_def),
                    },
                    "position": {"x": 0, "y": 0},
                })
                node_ids.append(art.id)
            stage_to_node_ids[stage_def.stage_key] = node_ids

        elif len(stage_arts) == 1:
            # Single artifact exists for this stage
            art = stage_arts[0]
            matching_exec = next(
                (e for e in stage_execs if e.artifact_id == art.id), None
            )
            is_active = bool(
                matching_exec
                and matching_exec.status in (StageStatus.RUNNING, StageStatus.AI_REVIEW)
            )
            nodes.append({
                "id": art.id,
                "type": "stageNode",
                "data": {
                    "label": art.name,
                    "artifact_type": art.artifact_type.value,
                    "status": art.status.value,
                    "component_key": art.component_key,
                    "version": art.version,
                    "stage_key": stage_def.stage_key,
                    "is_active": is_active,
                    "has_artifact": True,
                    "prompt_info": _build_prompt_info(stage_def),
                },
                "position": {"x": 0, "y": 0},
            })
            stage_to_node_ids[stage_def.stage_key] = [art.id]

        else:
            # No artifacts yet — show placeholder node from stage definition
            status = "pending"
            is_active = False
            if stage_execs:
                if any(e.status == StageStatus.RUNNING for e in stage_execs):
                    status = "running"
                    is_active = True
                elif any(e.status == StageStatus.AI_REVIEW for e in stage_execs):
                    status = "ai_reviewing"
                    is_active = True
                elif any(e.status == StageStatus.AWAITING_REVIEW for e in stage_execs):
                    status = "awaiting_review"
                elif any(e.status == StageStatus.APPROVED for e in stage_execs):
                    status = "approved"
                elif any(e.status == StageStatus.FAILED for e in stage_execs):
                    status = "failed"

            node_id = f"stage_{stage_def.stage_key}"
            nodes.append({
                "id": node_id,
                "type": "stageNode",
                "data": {
                    "label": stage_def.display_name,
                    "artifact_type": stage_def.output_artifact_type,
                    "status": status,
                    "component_key": None,
                    "version": 0,
                    "stage_key": stage_def.stage_key,
                    "is_active": is_active,
                    "has_artifact": False,
                    "prompt_info": _build_prompt_info(stage_def),
                },
                "position": {"x": 0, "y": 0},
            })
            stage_to_node_ids[stage_def.stage_key] = [node_id]

    # Build edges from stage input_stage_keys
    edges: list[dict] = []
    edge_idx = 0
    for stage_def in stages:
        target_ids = stage_to_node_ids.get(stage_def.stage_key, [])
        for input_key in stage_def.input_stage_keys:
            source_ids = stage_to_node_ids.get(input_key, [])
            for src_id in source_ids:
                for tgt_id in target_ids:
                    # For component-specific nodes, only connect matching components
                    src_node = next((n for n in nodes if n["id"] == src_id), None)
                    tgt_node = next((n for n in nodes if n["id"] == tgt_id), None)
                    if not src_node or not tgt_node:
                        continue
                    src_comp = src_node["data"]["component_key"]
                    tgt_comp = tgt_node["data"]["component_key"]
                    if src_comp and tgt_comp and src_comp != tgt_comp:
                        continue

                    is_animated = (
                        src_node["data"].get("is_active", False)
                        or tgt_node["data"].get("is_active", False)
                    )
                    edges.append({
                        "id": f"edge_{edge_idx}",
                        "source": src_id,
                        "target": tgt_id,
                        "type": "default",
                        "animated": is_animated,
                    })
                    edge_idx += 1

    return {"nodes": nodes, "edges": edges}
