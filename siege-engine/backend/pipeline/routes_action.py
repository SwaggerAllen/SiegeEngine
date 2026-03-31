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

            req = ResumeRunRequest(
                ai_loops=action.ai_loops,
                stop_point=action.stop_point,
                start_stage_key=action.start_stage_key,
                start_component_key=action.start_component_key,
            )
            return await resume_run(project_id, req, db, user)

        case "propagate":
            from backend.pipeline.routes_pipeline import propagate_changes

            return await propagate_changes(project_id, db, user)

        case "cancel":
            from backend.pipeline.routes_pipeline import cancel_pipeline
            from backend.pipeline.schemas import CancelRequest

            req = CancelRequest(
                open_pr=action.open_pr,
                pr_title=action.pr_title,
                pr_body=action.pr_body,
                base_branch=action.base_branch,
            )
            return await cancel_pipeline(project_id, req, db, user)

        case "reset_all":
            from backend.pipeline.routes_pipeline import reset_all

            return await reset_all(project_id, db, user)

        # ── Stage actions ──
        case "resume_stage":
            from backend.pipeline.routes_stage import resume_stage
            from backend.pipeline.schemas import ResumeRequest

            req = ResumeRequest(
                execution_id=action.execution_id,
                action=action.action,
                notes=action.notes,
                edited_content=action.edited_content,
            )
            return await resume_stage(project_id, req, db, user)

        case "revise":
            from backend.pipeline.routes_stage import revise_artifact
            from backend.pipeline.schemas import ReviseRequest

            req = ReviseRequest(
                artifact_id=action.artifact_id,
                feedback=action.feedback,
            )
            return await revise_artifact(project_id, req, db, user)

        case "resolve_stale":
            from backend.pipeline.routes_stage import resolve_stale
            from backend.pipeline.schemas import ResolveStaleRequest

            req = ResolveStaleRequest(
                artifact_id=action.artifact_id,
                action=action.action,
                notes=action.notes,
                edited_content=action.edited_content,
            )
            return await resolve_stale(project_id, req, db, user)

        case "regen_downstream":
            from backend.pipeline.routes_stage import regen_downstream
            from backend.pipeline.schemas import RegenDownstreamRequest

            req = RegenDownstreamRequest(artifact_id=action.artifact_id)
            return await regen_downstream(project_id, req, db, user)

        case "cancel_stage":
            from backend.pipeline.routes_stage import cancel_stage

            return await cancel_stage(project_id, action.execution_id, db, user)

        case "force_restart":
            from backend.pipeline.routes_stage import force_restart_stage

            return await force_restart_stage(project_id, action.execution_id, db, user)

        case "trigger_stage":
            from backend.pipeline.routes_stage import trigger_stage
            from backend.pipeline.schemas import TriggerStageRequest

            req = TriggerStageRequest(
                stage_key=action.stage_key,
                component_key=action.component_key,
            )
            return await trigger_stage(project_id, req, db, user)

        case "retry":
            from backend.pipeline.routes_pipeline import retry_stage

            return await retry_stage(project_id, action.execution_id, db, user)

        # ── Artifact actions ──
        case "prune":
            from backend.pipeline.routes_pipeline import prune_artifact

            return await prune_artifact(project_id, action.artifact_id, db, user)

        case "reparse":
            from backend.pipeline.routes_pipeline import reparse_fanout

            return await reparse_fanout(project_id, action.artifact_id, db, user)

        case "regenerate":
            from backend.pipeline.routes_pipeline import regenerate
            from backend.pipeline.schemas import RegenerateRequest

            req = RegenerateRequest(artifact_ids=action.artifact_ids)
            return await regenerate(project_id, req, db, user)

        case "prompt_preview":
            from backend.pipeline.routes_pipeline import prompt_preview
            from backend.pipeline.schemas import PromptPreviewRequest

            req = PromptPreviewRequest(
                artifact_id=action.artifact_id,
                human_notes=action.human_notes,
            )
            return prompt_preview(project_id, req, db, user)

        case "retry_summary":
            import asyncio

            from backend.models import Artifact
            from backend.pipeline import events as evt
            from backend.pipeline.event_store import EventStore
            from backend.pipeline.websocket import ws_manager

            artifact = db.get(Artifact, action.artifact_id)
            if not artifact:
                return {"status": "error", "detail": "Artifact not found"}

            # Find the execution for event context
            from backend.models import StageExecution
            execution = (
                db.query(StageExecution)
                .filter_by(artifact_id=action.artifact_id)
                .order_by(StageExecution.completed_at.desc())
                .first()
            )

            event_store = EventStore(db)

            # Capture current snapshot status so we can restore after summarizing
            snapshot = event_store.get_snapshot(project_id)
            current_artifact_status = (snapshot.artifact_statuses or {}).get(
                action.artifact_id, artifact.status.value
            )

            event_params = {
                "execution_id": execution.id if execution else None,
                "stage_key": execution.stage_key if execution else None,
                "component_key": execution.component_key if execution else None,
                "artifact_id": action.artifact_id,
            }
            run_id = execution.run_id if execution else None

            # Emit SUMMARY_STARTED and commit so the status is visible immediately
            event_store.emit(project_id, evt.SUMMARY_STARTED, event_params, run_id=run_id)
            db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "summary_started",
                "artifact_id": action.artifact_id,
                "stage_key": event_params["stage_key"],
                "component_key": event_params["component_key"],
            })

            # Run the actual summary generation in a background task so the
            # HTTP response returns immediately and the UI shows "summarizing".
            async def _run_summary_bg(
                _project_id: str,
                _artifact_id: str,
                _event_params: dict,
                _run_id: str | None,
                _restore_status: str,
            ):
                from backend.database import SessionLocal
                from backend.pipeline.summarize import generate_summary

                bg_db = SessionLocal()
                try:
                    summary = await generate_summary(_artifact_id, bg_db)
                    summary_event = evt.SUMMARY_COMPLETED if summary else evt.SUMMARY_FAILED
                except Exception:
                    logger.warning("Background summary generation failed for %s", _artifact_id, exc_info=True)
                    summary = None
                    summary_event = evt.SUMMARY_FAILED

                try:
                    bg_store = EventStore(bg_db)
                    completion_params = {**_event_params, "restore_status": _restore_status}
                    bg_store.emit(_project_id, summary_event, completion_params, run_id=_run_id)
                    bg_db.commit()

                    await ws_manager.broadcast(_project_id, {
                        "type": "summary_completed" if summary else "summary_failed",
                        "artifact_id": _artifact_id,
                        "stage_key": _event_params.get("stage_key"),
                        "component_key": _event_params.get("component_key"),
                    })
                except Exception:
                    logger.error("Failed to emit summary completion event", exc_info=True)
                    bg_db.rollback()
                finally:
                    bg_db.close()

            asyncio.create_task(_run_summary_bg(
                project_id,
                action.artifact_id,
                event_params,
                run_id,
                current_artifact_status,
            ))

            return {"status": "ok", "started": True}

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
