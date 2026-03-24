import graphlib as _graphlib
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


def _get_latest_run_executions(
    db: Session, project_id: str
) -> tuple[PipelineRun | None, list[StageExecution]]:
    """Return (latest_run, executions) for a project.

    Includes executions from the latest pipeline run **plus** any executions
    that started after it (out-of-run activity such as stale approvals,
    revisions, or post-run reviews).  This ensures the DAG reflects the
    current state even when actions happen outside a formal run.
    """
    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )
    if not latest_run:
        return None, db.query(StageExecution).filter_by(project_id=project_id).all()

    # Executions belonging to the latest run
    run_execs = (
        db.query(StageExecution)
        .filter_by(project_id=project_id, run_id=latest_run.run_id)
        .all()
    )

    # Also include executions that don't belong to this run but started
    # after the run was created (out-of-run approvals, revisions, etc.)
    out_of_run_execs = (
        db.query(StageExecution)
        .filter(
            StageExecution.project_id == project_id,
            StageExecution.run_id != latest_run.run_id,
            StageExecution.started_at > latest_run.started_at,
        )
        .all()
    )

    return latest_run, run_execs + out_of_run_execs


def _check_acyclic(edges: list[dict]) -> None:
    """Raise ValueError if the edge list contains a directed cycle.

    Uses stdlib graphlib.TopologicalSorter which raises CycleError for cycles.
    """
    ts: _graphlib.TopologicalSorter[str] = _graphlib.TopologicalSorter()
    for e in edges:
        ts.add(e["target"], e["source"])
    try:
        # prepare() detects cycles immediately without full iteration
        ts.prepare()
    except _graphlib.CycleError as exc:
        raise ValueError(f"Cycle detected in DAG: {exc}") from exc


def build_dependency_graph(db: Session, project_id: str) -> dict[str, list[str]]:
    deps = (
        db.execute(
            select(ArtifactDependency)
            .join(Artifact, ArtifactDependency.upstream_artifact_id == Artifact.id)
            .where(Artifact.project_id == project_id)
        )
        .scalars()
        .all()
    )

    graph: dict[str, list[str]] = defaultdict(list)
    for dep in deps:
        graph[dep.upstream_artifact_id].append(dep.downstream_artifact_id)
    return graph


def propagate_staleness(db: Session, artifact_id: str, event_store=None) -> list[str]:
    """Propagate staleness to downstream artifacts via dependency graph.

    Emits STALENESS_PROPAGATED event (updates snapshot via reducer),
    then sets artifact.status = STALE as DB projection.
    event_store should always be provided; the parameter is optional only
    for backward compatibility during migration.
    """
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
            stale_ids.append(current_id)

        for downstream_id in graph.get(current_id, []):
            queue.append(downstream_id)

    # Emit staleness_propagated event FIRST (snapshot source of truth)
    if stale_ids and event_store:
        from backend.pipeline import events as evt
        event_store.emit(
            artifact.project_id, evt.STALENESS_PROPAGATED,
            {"source_artifact_id": artifact_id, "stale_ids": stale_ids},
        )

    # DB projection: set artifact.status = STALE
    for sid in stale_ids:
        art = db.get(Artifact, sid)
        if art:
            art.status = ArtifactStatus.STALE

    return stale_ids


def get_regeneration_order(db: Session, artifact_ids: list[str]) -> list[list[str]]:
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
    """Return IDs of stale artifacts using the snapshot as source of truth."""
    from backend.pipeline.event_store import EventStore
    es = EventStore(db)
    snapshot = es.get_snapshot(project_id)
    return [
        aid for aid, status in (snapshot.artifact_statuses or {}).items()
        if status == "stale"
    ]


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
        if (
            prev is None
            or (e.started_at or e.completed_at)
            and (not prev.started_at or (e.started_at and e.started_at > prev.started_at))
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
    if any(e.status == StageStatus.REJECTED for e in latest):
        return "rejected", False
    if any(e.status == StageStatus.AWAITING_REVIEW for e in latest):
        return "awaiting_review", False
    if all(e.status == StageStatus.APPROVED for e in latest):
        return "approved", False
    if any(e.status == StageStatus.APPROVED for e in latest):
        return "awaiting_review", False
    return "pending", False


def get_dag_visualization_data(db: Session, project_id: str) -> dict:
    """Build workflow DAG from stage definitions + snapshot.

    Shows one node per stage definition (workflow steps).
    Reads stage statuses from the snapshot (source of truth).
    """
    from backend.pipeline.event_store import EventStore

    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        return {"nodes": [], "edges": []}

    stages = sorted(config.stages, key=lambda s: s.order_index)
    snapshot = EventStore(db).get_snapshot(project_id)
    stage_statuses = snapshot.stage_statuses or {}

    nodes: list[dict] = []
    for stage_def in stages:
        # For workflow DAG, use the aggregate status for the stage key.
        # Fan-out stages may have multiple entries (stage_key/component_key),
        # so we aggregate: if any component is running, the stage is running, etc.
        status = _derive_stage_status_from_snapshot(stage_def.stage_key, stage_statuses)
        is_active = status in ("running", "ai_review", "ai_reviewing")

        node_id = f"stage_{stage_def.stage_key}"
        nodes.append(
            {
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
            }
        )

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
            is_animated = src_node["data"].get("is_active", False) or tgt_node["data"].get(
                "is_active", False
            )
            edges.append(
                {
                    "id": f"edge_{edge_idx}",
                    "source": src_id,
                    "target": tgt_id,
                    "type": "default",
                    "animated": is_animated,
                }
            )
            edge_idx += 1

    _check_acyclic(edges)
    return {"nodes": nodes, "edges": edges}


def _derive_stage_status_from_snapshot(
    stage_key: str, stage_statuses: dict[str, str]
) -> str:
    """Derive aggregate status for a stage from snapshot stage_statuses.

    Handles both non-fan-out (exact match) and fan-out (prefix match) stages.
    """
    # Exact match for non-fan-out stages
    if stage_key in stage_statuses:
        return stage_statuses[stage_key]

    # Fan-out: collect all entries that start with this stage_key
    prefix = f"{stage_key}/"
    component_statuses = [
        status for key, status in stage_statuses.items()
        if key.startswith(prefix)
    ]
    if not component_statuses:
        return "pending"

    # Priority-based aggregation (same logic as old _derive_stage_status)
    if any(s == "running" for s in component_statuses):
        return "running"
    if any(s == "ai_review" for s in component_statuses):
        return "ai_review"
    if any(s == "failed" for s in component_statuses):
        return "failed"
    if any(s == "rejected" for s in component_statuses):
        return "rejected"
    if any(s == "awaiting_review" for s in component_statuses):
        return "awaiting_review"
    if all(s == "approved" for s in component_statuses):
        return "approved"
    if any(s == "approved" for s in component_statuses):
        return "awaiting_review"
    return "pending"


def _find_artifact_node(nodes: list[dict], artifact_type: str, component_key: str) -> dict | None:
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

    Reads status from snapshot (source of truth). Structural data (artifact names,
    types, component_keys) comes from DB or snapshot.artifact_meta.
    Only shows documents that actually exist — the project document as root,
    then generated artifacts. Stages with no artifacts yet are omitted entirely.
    """
    from backend.pipeline.event_store import EventStore

    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        return {"nodes": [], "edges": []}

    stages = sorted(config.stages, key=lambda s: s.order_index)
    snapshot = EventStore(db).get_snapshot(project_id)
    artifact_statuses = snapshot.artifact_statuses or {}
    artifact_versions = snapshot.artifact_versions or {}
    stage_statuses = snapshot.stage_statuses or {}
    execution_map = snapshot.execution_map or {}

    artifacts = (
        db.execute(select(Artifact).where(Artifact.project_id == project_id)).scalars().all()
    )

    # Build lookups
    type_to_artifacts: dict[str, list] = defaultdict(list)
    for art in artifacts:
        type_to_artifacts[art.artifact_type.value].append(art)

    nodes: list[dict] = []
    stage_to_node_ids: dict[str, list[str]] = {}

    # Add project document as root node
    project_docs = type_to_artifacts.get(ArtifactType.PROJECT_DOC.value, [])
    if project_docs:
        doc = project_docs[0]
        doc_status = artifact_statuses.get(doc.id, doc.status.value)
        nodes.append(
            {
                "id": doc.id,
                "type": "stageNode",
                "data": {
                    "label": doc.name,
                    "artifact_type": doc.artifact_type.value,
                    "status": doc_status,
                    "component_key": None,
                    "version": artifact_versions.get(doc.id, doc.version),
                    "stage_key": "project_doc",
                    "is_active": False,
                    "has_artifact": True,
                    "prompt_info": None,
                },
                "position": {"x": 0, "y": 0},
            }
        )
        stage_to_node_ids["project_doc"] = [doc.id]

    # Build nodes for stages with artifacts, plus placeholders from snapshot
    for stage_def in stages:
        stage_arts = type_to_artifacts.get(stage_def.output_artifact_type, [])
        node_ids = []

        # Nodes for existing artifacts — status from snapshot
        for art in stage_arts:
            art_status = artifact_statuses.get(art.id, art.status.value)
            # Derive composite key for stage status / execution lookup
            comp_key = (
                f"{stage_def.stage_key}/{art.component_key}"
                if art.component_key else stage_def.stage_key
            )
            stage_status = stage_statuses.get(comp_key)
            is_active = stage_status in ("running", "ai_review")
            exec_entry = execution_map.get(comp_key, {})
            execution_id = exec_entry.get("execution_id")

            nodes.append(
                {
                    "id": art.id,
                    "type": "stageNode",
                    "data": {
                        "label": art.name,
                        "artifact_type": art.artifact_type.value,
                        "status": art_status,
                        "component_key": art.component_key,
                        "version": artifact_versions.get(art.id, art.version),
                        "stage_key": stage_def.stage_key,
                        "is_active": is_active,
                        "has_artifact": True,
                        "prompt_info": _build_prompt_info(stage_def),
                        "execution_id": execution_id,
                        "execution_status": stage_status,
                    },
                    "position": {"x": 0, "y": 0},
                }
            )
            node_ids.append(art.id)

        # Placeholder nodes for running/reviewing/failed stages with no artifact yet
        # Use snapshot execution_map to find stages that have executions but no artifacts
        art_comp_keys = {art.component_key for art in stage_arts}
        for snap_key, snap_status in stage_statuses.items():
            # Match stage keys that belong to this stage_def
            if snap_key == stage_def.stage_key:
                comp_key_val = None
            elif snap_key.startswith(f"{stage_def.stage_key}/"):
                comp_key_val = snap_key[len(stage_def.stage_key) + 1:]
            else:
                continue

            if snap_status not in ("running", "ai_review", "failed"):
                continue
            if comp_key_val in art_comp_keys:
                continue
            if comp_key_val is None and None in art_comp_keys:
                continue

            exec_entry = execution_map.get(snap_key, {})
            exec_id = exec_entry.get("execution_id", snap_key)
            placeholder_id = f"placeholder_{exec_id}"
            label = stage_def.display_name
            if comp_key_val:
                label = f"{label} - {comp_key_val}"
            if snap_status == "failed":
                display_status = "failed"
                is_placeholder_active = False
            elif snap_status == "ai_review":
                display_status = "ai_reviewing"
                is_placeholder_active = True
            else:
                display_status = "generating"
                is_placeholder_active = True
            nodes.append(
                {
                    "id": placeholder_id,
                    "type": "stageNode",
                    "data": {
                        "label": label,
                        "artifact_type": stage_def.output_artifact_type,
                        "status": display_status,
                        "component_key": comp_key_val,
                        "version": 0,
                        "stage_key": stage_def.stage_key,
                        "is_active": is_placeholder_active,
                        "has_artifact": False,
                        "prompt_info": _build_prompt_info(stage_def),
                        "execution_id": exec_entry.get("execution_id"),
                        "execution_status": snap_status,
                    },
                    "position": {"x": 0, "y": 0},
                }
            )
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
                        # Allow parent-child edges (e.g. "a" -> "a.b")
                        if not (
                            tgt_comp.startswith(src_comp + ".")
                            or src_comp.startswith(tgt_comp + ".")
                        ):
                            continue

                    is_animated = src_node["data"].get("is_active", False) or tgt_node["data"].get(
                        "is_active", False
                    )
                    edges.append(
                        {
                            "id": f"edge_{edge_idx}",
                            "source": src_id,
                            "target": tgt_id,
                            "type": "default",
                            "animated": is_animated,
                        }
                    )
                    edge_idx += 1

    # Add cross-component dependency edges from ComponentDefinition.
    # Draw edges at every artifact tier so the dependency relationship is
    # visible as soon as both components have at least one artifact.
    _COMPONENT_DEP_PAIRS = [
        (ArtifactType.COMPONENT_REQUIREMENTS.value, ArtifactType.COMPONENT_REQUIREMENTS.value),
        (ArtifactType.COMPONENT_ARCHITECTURE.value, ArtifactType.COMPONENT_REQUIREMENTS.value),
        (ArtifactType.COMPONENT_ARCHITECTURE.value, ArtifactType.COMPONENT_ARCHITECTURE.value),
        (ArtifactType.COMPONENT_ARCHITECTURE.value, ArtifactType.COMPONENT_PLAN.value),
        (ArtifactType.COMPONENT_PLAN.value, ArtifactType.COMPONENT_PLAN.value),
    ]
    _SC_REQ = ArtifactType.SUB_COMPONENT_REQUIREMENTS.value
    _SC_ARCH = ArtifactType.SUB_COMPONENT_ARCHITECTURE.value
    _SC_PLAN = ArtifactType.SUB_COMPONENT_PLAN.value
    _SUB_COMPONENT_DEP_PAIRS = [
        (_SC_REQ, _SC_REQ),
        (_SC_ARCH, _SC_REQ),
        (_SC_ARCH, _SC_ARCH),
        (_SC_ARCH, _SC_PLAN),
        (_SC_PLAN, _SC_PLAN),
    ]
    existing_edge_keys = {(e["source"], e["target"]) for e in edges}
    comp_defs = db.query(ComponentDefinition).filter_by(project_id=project_id).all()
    for comp_def in comp_defs:
        for dep_key in comp_def.dependencies or []:
            if comp_def.parent_key:
                dep_full_key = f"{comp_def.parent_key}.{dep_key}"
                comp_full_key = f"{comp_def.parent_key}.{comp_def.key}"
                pairs = _SUB_COMPONENT_DEP_PAIRS
            else:
                dep_full_key = dep_key
                comp_full_key = comp_def.key
                pairs = _COMPONENT_DEP_PAIRS

            for src_type, tgt_type in pairs:
                src_node = _find_artifact_node(nodes, src_type, dep_full_key)
                tgt_node = _find_artifact_node(nodes, tgt_type, comp_full_key)
                if src_node and tgt_node:
                    edge_key = (src_node["id"], tgt_node["id"])
                    if edge_key not in existing_edge_keys:
                        existing_edge_keys.add(edge_key)
                        edges.append(
                            {
                                "id": f"dep_edge_{edge_idx}",
                                "source": src_node["id"],
                                "target": tgt_node["id"],
                                "type": "default",
                                "animated": False,
                                "style": {"strokeDasharray": "5 5", "stroke": "#818cf8"},
                            }
                        )
                        edge_idx += 1

    _check_acyclic(edges)
    return {"nodes": nodes, "edges": edges}
