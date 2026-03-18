from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    Artifact,
    ArtifactDependency,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    PipelineConfig,
    PipelineRun,
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


def _latest_executions(stage_execs: list) -> list:
    """Keep only the most recent execution per component_key.

    When a stage is retried, multiple executions exist for the same
    component_key.  Only the latest one reflects the current state.
    """
    best: dict[str | None, StageExecution] = {}
    for e in stage_execs:
        prev = best.get(e.component_key)
        if prev is None or (e.started_at or e.completed_at) and (
            not prev.started_at or (e.started_at and e.started_at > prev.started_at)
        ):
            best[e.component_key] = e
    return list(best.values())


def _derive_stage_status(stage_execs: list) -> tuple[str, bool]:
    """Derive aggregate status and is_active flag from a stage's executions."""
    if not stage_execs:
        return "pending", False
    # Only consider the latest execution per component to avoid stale
    # FAILED / AWAITING_REVIEW entries from retries masking current state.
    latest = _latest_executions(stage_execs)
    if any(e.status == StageStatus.RUNNING for e in latest):
        return "running", True
    if any(e.status == StageStatus.AI_REVIEW for e in latest):
        return "ai_reviewing", True
    if any(e.status == StageStatus.FAILED for e in latest):
        return "failed", False
    if any(e.status == StageStatus.AWAITING_REVIEW for e in latest):
        return "awaiting_review", False
    if all(e.status == StageStatus.APPROVED for e in latest):
        return "approved", False
    if any(e.status == StageStatus.APPROVED for e in latest):
        return "awaiting_review", False
    return "pending", False


def get_dag_visualization_data(db: Session, project_id: str) -> dict:
    """Build workflow DAG from stage definitions.

    Shows one node per stage definition (workflow steps).
    Never expands to per-artifact or per-component nodes.
    """
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        return {"nodes": [], "edges": []}

    stages = sorted(config.stages, key=lambda s: s.order_index)

    # Only consider executions from the latest pipeline run so that old
    # FAILED / AWAITING_REVIEW records don't mask the current state.
    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )
    exec_query = db.query(StageExecution).filter_by(project_id=project_id)
    if latest_run:
        exec_query = exec_query.filter_by(run_id=latest_run.run_id)
    executions = exec_query.all()

    key_to_execs: dict[str, list] = defaultdict(list)
    for exc in executions:
        key_to_execs[exc.stage_key].append(exc)

    nodes: list[dict] = []
    for stage_def in stages:
        stage_execs = key_to_execs.get(stage_def.stage_key, [])
        status, is_active = _derive_stage_status(stage_execs)

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

    # Build edges from input_stage_keys (one node per stage, simple)
    edges: list[dict] = []
    edge_idx = 0
    for stage_def in stages:
        tgt_id = f"stage_{stage_def.stage_key}"
        for input_key in stage_def.input_stage_keys:
            src_id = f"stage_{input_key}"
            tgt_node = next((n for n in nodes if n["id"] == tgt_id), None)
            src_node = next((n for n in nodes if n["id"] == src_id), None)
            if not src_node or not tgt_node:
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


def _find_artifact_node(
    nodes: list[dict], artifact_type: str, component_key: str
) -> dict | None:
    """Find a node by artifact type and component key."""
    for node in nodes:
        if (
            node["data"].get("artifact_type") == artifact_type
            and node["data"].get("component_key") == component_key
        ):
            return node
    return None


def get_documents_dag(db: Session, project_id: str) -> dict:
    """Build documents DAG showing artifact lineage.

    Only shows documents that actually exist — the project document as root,
    then generated artifacts. Stages with no artifacts yet are omitted entirely.
    """
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        return {"nodes": [], "edges": []}

    stages = sorted(config.stages, key=lambda s: s.order_index)

    artifacts = db.execute(
        select(Artifact).where(Artifact.project_id == project_id)
    ).scalars().all()

    # Only consider executions from the latest pipeline run.
    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )
    exec_query = db.query(StageExecution).filter_by(project_id=project_id)
    if latest_run:
        exec_query = exec_query.filter_by(run_id=latest_run.run_id)
    executions = exec_query.all()

    # Build lookups
    type_to_artifacts: dict[str, list] = defaultdict(list)
    for art in artifacts:
        type_to_artifacts[art.artifact_type.value].append(art)

    key_to_execs: dict[str, list] = defaultdict(list)
    for exc in executions:
        key_to_execs[exc.stage_key].append(exc)

    nodes: list[dict] = []
    stage_to_node_ids: dict[str, list[str]] = {}

    # Add project document as root node
    project_docs = type_to_artifacts.get(ArtifactType.PROJECT_DOC.value, [])
    if project_docs:
        doc = project_docs[0]
        nodes.append({
            "id": doc.id,
            "type": "stageNode",
            "data": {
                "label": doc.name,
                "artifact_type": doc.artifact_type.value,
                "status": doc.status.value,
                "component_key": None,
                "version": doc.version,
                "stage_key": "project_doc",
                "is_active": False,
                "has_artifact": True,
                "prompt_info": None,
            },
            "position": {"x": 0, "y": 0},
        })
        stage_to_node_ids["project_doc"] = [doc.id]

    # Build nodes for stages with artifacts, plus placeholders for running executions
    for stage_def in stages:
        stage_arts = type_to_artifacts.get(stage_def.output_artifact_type, [])
        stage_execs = key_to_execs.get(stage_def.stage_key, [])
        node_ids = []

        # Keep only the latest execution per component_key for accurate status
        latest_stage_execs = _latest_executions(stage_execs)

        # Nodes for existing artifacts
        for art in stage_arts:
            matching_exec = next(
                (e for e in latest_stage_execs if e.component_key == art.component_key or e.artifact_id == art.id),
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
                    "execution_id": matching_exec.id if matching_exec else None,
                    "execution_status": matching_exec.status.value if matching_exec else None,
                },
                "position": {"x": 0, "y": 0},
            })
            node_ids.append(art.id)

        # Placeholder nodes for running/reviewing/failed executions with no artifact yet
        art_comp_keys = {art.component_key for art in stage_arts}
        for exc in latest_stage_execs:
            if exc.status not in (StageStatus.RUNNING, StageStatus.AI_REVIEW, StageStatus.FAILED):
                continue
            if exc.component_key in art_comp_keys:
                continue  # Already has an artifact node
            # Also skip if a None-keyed artifact already exists for non-fan-out stages
            if exc.component_key is None and None in art_comp_keys:
                continue

            placeholder_id = f"placeholder_{exc.id}"
            label = stage_def.display_name
            if exc.component_key:
                label = f"{label} - {exc.component_key}"
            if exc.status == StageStatus.FAILED:
                status = "failed"
                is_placeholder_active = False
            else:
                status = "generating" if exc.status == StageStatus.RUNNING else "ai_reviewing"
                is_placeholder_active = True
            nodes.append({
                "id": placeholder_id,
                "type": "stageNode",
                "data": {
                    "label": label,
                    "artifact_type": stage_def.output_artifact_type,
                    "status": status,
                    "component_key": exc.component_key,
                    "version": 0,
                    "stage_key": stage_def.stage_key,
                    "is_active": is_placeholder_active,
                    "has_artifact": False,
                    "prompt_info": _build_prompt_info(stage_def),
                    "execution_id": exc.id,
                    "execution_status": exc.status.value,
                },
                "position": {"x": 0, "y": 0},
            })
            node_ids.append(placeholder_id)

        if node_ids:
            stage_to_node_ids[stage_def.stage_key] = node_ids

    # Build edges only between stages that have nodes
    edges: list[dict] = []
    edge_idx = 0
    for stage_def in stages:
        target_ids = stage_to_node_ids.get(stage_def.stage_key, [])
        if not target_ids:
            continue

        input_keys = stage_def.input_stage_keys if stage_def.input_stage_keys else ["project_doc"]

        for input_key in input_keys:
            source_ids = stage_to_node_ids.get(input_key, [])
            for src_id in source_ids:
                for tgt_id in target_ids:
                    src_node = next((n for n in nodes if n["id"] == src_id), None)
                    tgt_node = next((n for n in nodes if n["id"] == tgt_id), None)
                    if not src_node or not tgt_node:
                        continue
                    src_comp = src_node["data"]["component_key"]
                    tgt_comp = tgt_node["data"]["component_key"]
                    if src_comp and tgt_comp and src_comp != tgt_comp:
                        # Allow parent→child edges (e.g., "auth_service" → "auth_service.token_manager")
                        if not (tgt_comp.startswith(src_comp + ".") or src_comp.startswith(tgt_comp + ".")):
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

    # Add cross-component dependency edges from ComponentDefinition
    comp_defs = (
        db.query(ComponentDefinition)
        .filter_by(project_id=project_id)
        .all()
    )
    for comp_def in comp_defs:
        for dep_key in (comp_def.dependencies or []):
            if comp_def.parent_key:
                # Sub-component dependency
                src_type = ArtifactType.SUB_COMPONENT_ARCHITECTURE.value
                tgt_type = ArtifactType.SUB_COMPONENT_REQUIREMENTS.value
                dep_full_key = f"{comp_def.parent_key}.{dep_key}"
                comp_full_key = f"{comp_def.parent_key}.{comp_def.key}"
            else:
                # Top-level component dependency
                src_type = ArtifactType.COMPONENT_ARCHITECTURE.value
                tgt_type = ArtifactType.COMPONENT_REQUIREMENTS.value
                dep_full_key = dep_key
                comp_full_key = comp_def.key

            src_node = _find_artifact_node(nodes, src_type, dep_full_key)
            tgt_node = _find_artifact_node(nodes, tgt_type, comp_full_key)
            if src_node and tgt_node:
                edges.append({
                    "id": f"dep_edge_{edge_idx}",
                    "source": src_node["id"],
                    "target": tgt_node["id"],
                    "type": "default",
                    "animated": False,
                    "style": {"strokeDasharray": "5 5", "stroke": "#818cf8"},
                })
                edge_idx += 1

    return {"nodes": nodes, "edges": edges}
