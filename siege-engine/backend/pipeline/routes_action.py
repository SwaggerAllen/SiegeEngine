"""Unified POST /action endpoint for all pipeline mutations.

Replaces 19+ individual POST/DELETE endpoints with a single discriminated
union endpoint.  Each action type dispatches to the same handler logic
that previously lived in routes_pipeline.py and routes_stage.py.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer
from backend.database import get_db
from backend.models import User
from backend.pipeline.schemas import PipelineAction

logger = logging.getLogger(__name__)

action_router = APIRouter()


@action_router.post("/{project_id}/action")
async def pipeline_action(
    project_id: str,
    action: PipelineAction,
    db: Session = Depends(get_db),
    user: User = Depends(_require_writer),
):
    """Single mutation endpoint for all pipeline actions.

    The `type` field in the request body determines which action to perform.
    See PipelineAction union type for all supported action types.
    """
    match action.type:
        # ── Pipeline lifecycle ──
        case "start":
            from backend.pipeline.routes_pipeline import start_pipeline
            from backend.pipeline.schemas import PipelineStartRequest

            req = PipelineStartRequest(
                ai_loops=action.ai_loops,
                stop_point=action.stop_point,
                start_stage_key=action.start_stage_key,
                start_component_key=action.start_component_key,
            )
            return await start_pipeline(project_id, req, db, user)

        case "resume_run":
            from backend.pipeline.routes_pipeline import resume_run
            from backend.pipeline.schemas import ResumeRunRequest

            resume_run_req = ResumeRunRequest(
                ai_loops=action.ai_loops,
                stop_point=action.stop_point,
                start_stage_key=action.start_stage_key,
                start_component_key=action.start_component_key,
            )
            return await resume_run(project_id, resume_run_req, db, user)

        case "propagate":
            from backend.pipeline.routes_pipeline import propagate_changes

            return await propagate_changes(project_id, db, user)

        case "cancel":
            from backend.pipeline.routes_pipeline import cancel_pipeline
            from backend.pipeline.schemas import CancelRequest

            cancel_req = CancelRequest(
                open_pr=action.open_pr,
                pr_title=action.pr_title,
                pr_body=action.pr_body,
                base_branch=action.base_branch,
            )
            return await cancel_pipeline(project_id, cancel_req, db, user)

        case "reset_all":
            from backend.pipeline.routes_pipeline import reset_all

            return await reset_all(project_id, db, user)

        # ── Stage actions ──
        case "resume_stage":
            from backend.pipeline.routes_stage import resume_stage
            from backend.pipeline.schemas import ResumeRequest

            resume_req = ResumeRequest(
                execution_id=action.execution_id,
                action=action.action,
                notes=action.notes,
                edited_content=action.edited_content,
            )
            return await resume_stage(project_id, resume_req, db, user)

        case "revise":
            from backend.pipeline.routes_stage import revise_artifact
            from backend.pipeline.schemas import ReviseRequest

            revise_req = ReviseRequest(
                artifact_id=action.artifact_id,
                feedback=action.feedback,
            )
            return await revise_artifact(project_id, revise_req, db, user)

        case "resolve_stale":
            from backend.pipeline.routes_stage import resolve_stale
            from backend.pipeline.schemas import ResolveStaleRequest

            resolve_req = ResolveStaleRequest(
                artifact_id=action.artifact_id,
                action=action.action,
                notes=action.notes,
                edited_content=action.edited_content,
            )
            return await resolve_stale(project_id, resolve_req, db, user)

        case "regen_downstream":
            from backend.pipeline.routes_stage import regen_downstream
            from backend.pipeline.schemas import RegenDownstreamRequest

            regen_ds_req = RegenDownstreamRequest(artifact_id=action.artifact_id)
            return await regen_downstream(project_id, regen_ds_req, db, user)

        case "cancel_stage":
            from backend.pipeline.routes_stage import cancel_stage

            return await cancel_stage(project_id, action.execution_id, db, user)

        case "force_restart":
            from backend.pipeline.routes_stage import force_restart_stage

            return await force_restart_stage(project_id, action.execution_id, db, user)

        case "trigger_stage":
            from backend.pipeline.routes_stage import trigger_stage
            from backend.pipeline.schemas import TriggerStageRequest

            trig_req = TriggerStageRequest(
                stage_key=action.stage_key,
                component_key=action.component_key,
            )
            return await trigger_stage(project_id, trig_req, db, user)

        case "retry":
            from backend.pipeline.routes_pipeline import retry_stage

            return await retry_stage(project_id, action.execution_id, db, user)

        # ── Artifact actions ──
        case "prune":
            from backend.pipeline.routes_pipeline import prune_artifact

            return await prune_artifact(project_id, action.artifact_id, db, user)

        case "prune_descendants":
            from backend.pipeline.routes_pipeline import prune_descendants

            return await prune_descendants(project_id, action.stage_key, db, user)

        case "reparse":
            from backend.pipeline.routes_pipeline import reparse_fanout

            return await reparse_fanout(project_id, action.artifact_id, db, user)

        case "regenerate":
            from backend.pipeline.routes_pipeline import regenerate
            from backend.pipeline.schemas import RegenerateRequest

            regenerate_req = RegenerateRequest(artifact_ids=action.artifact_ids)
            return await regenerate(project_id, regenerate_req, db, user)

        case "prompt_preview":
            from backend.pipeline.routes_pipeline import prompt_preview
            from backend.pipeline.schemas import PromptPreviewRequest

            preview_req = PromptPreviewRequest(
                artifact_id=action.artifact_id,
                human_notes=action.human_notes,
            )
            return prompt_preview(project_id, preview_req, db, user)

        case "consolidate":
            from backend.pipeline.queue import enqueue

            enqueue(
                db,
                "consolidate_artifact",
                {"artifact_id": action.artifact_id},
            )
            return {"status": "consolidation_started"}

        case "retry_summary":
            from backend.models import Artifact
            from backend.pipeline.queue import enqueue

            artifact = db.get(Artifact, action.artifact_id)
            if not artifact:
                return {"status": "error", "detail": "Artifact not found"}

            job_id = enqueue(
                db,
                "generate_summary",
                {
                    "project_id": project_id,
                    "artifact_id": action.artifact_id,
                },
            )

            return {"status": "ok", "job_id": job_id}

        # ── Admin / recovery ──
        case "reconcile":
            from backend.pipeline.routes_pipeline import reconcile_statuses

            return reconcile_statuses(project_id, db, user)

        case "reconstruct":
            from backend.pipeline.routes_pipeline import reconstruct_from_git

            return reconstruct_from_git(project_id, db, user)

        case "revert":
            from backend.pipeline.routes_pipeline import revert_to_sequence

            return revert_to_sequence(project_id, action.sequence, db, user)

        # ── Blocking PR ──
        case "check_blocking_pr":
            from backend.pipeline.routes_pipeline import check_blocking_pr

            return await check_blocking_pr(project_id, db, user)

        case "dismiss_blocking_pr":
            from backend.pipeline.routes_pipeline import dismiss_blocking_pr

            return dismiss_blocking_pr(project_id, db, user)
