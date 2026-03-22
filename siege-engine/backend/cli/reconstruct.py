"""Reconstruct minimal pipeline state from a project's git repository.

Safety net for disaster recovery: if the database is corrupted or the
event log drifts, this command rebuilds Artifact records from the files
in the git repo plus the siege-state.json manifest.

Usage:
    python -m backend.cli.reconstruct <project_id> [--commit <sha>]

All existing artifacts, executions, events, and snapshots for the project
are wiped and rebuilt.  Document *content* is preserved because it lives
in the git repo.
"""

import argparse
import json
import logging
import sys

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    StageExecution,
)
from backend.models.pipeline_events import PipelineEvent, PipelineSnapshot

logger = logging.getLogger(__name__)


def reconstruct_from_git(
    db: Session,
    project_id: str,
    commit_sha: str | None = None,
) -> dict:
    """Rebuild pipeline state from the git repository.

    Steps:
    1. Read siege-state.json from the specified commit (or HEAD)
    2. Delete all existing pipeline state for the project
    3. Recreate Artifact records with content from git
    4. Recreate ComponentDefinition records
    5. Create a fresh PipelineSnapshot with everything AWAITING_REVIEW
    6. Emit a pipeline_reset event

    Returns a summary dict with counts.
    """
    from backend.git_manager.service import git_manager

    # ── Step 1: Read siege-state.json ─────────────────────────────────
    ref = commit_sha or "HEAD"
    try:
        state_json = git_manager.get_file_at_version(
            project_id, "siege-state.json", ref
        )
        state = json.loads(state_json)
    except Exception as e:
        raise ValueError(
            f"Cannot read siege-state.json at {ref} for project {project_id}: {e}"
        ) from e

    logger.info(
        "Reconstructing project %s from commit %s (run #%s)",
        project_id,
        ref,
        state.get("run_number", "?"),
    )

    # ── Step 2: Delete existing pipeline state ────────────────────────
    # Order matters for FK constraints
    db.query(ArtifactComment).filter_by(project_id=project_id).delete()
    db.query(ArtifactDependency).filter(
        ArtifactDependency.upstream_artifact_id.in_(
            db.query(Artifact.id).filter_by(project_id=project_id)
        )
        | ArtifactDependency.downstream_artifact_id.in_(
            db.query(Artifact.id).filter_by(project_id=project_id)
        )
    ).delete(synchronize_session="fetch")
    db.query(StageExecution).filter_by(project_id=project_id).delete()
    db.query(Artifact).filter_by(project_id=project_id).delete()
    db.query(PipelineEvent).filter_by(project_id=project_id).delete()
    db.query(PipelineSnapshot).filter_by(project_id=project_id).delete()
    db.query(ComponentDefinition).filter_by(project_id=project_id).delete()
    db.flush()

    # ── Step 3: Recreate artifacts from siege-state.json ──────────────
    artifact_count = 0
    snapshot_artifact_statuses = {}

    for art_data in state.get("artifacts", []):
        # Read content from git
        content = None
        file_path = art_data.get("file_path")
        if file_path:
            try:
                content = git_manager.get_file_at_version(
                    project_id, file_path, ref
                )
            except Exception:
                logger.warning(
                    "Could not read artifact file %s from git, skipping content",
                    file_path,
                )

        # Parse artifact type
        art_type_str = art_data.get("artifact_type", "")
        try:
            art_type = ArtifactType(art_type_str)
        except ValueError:
            logger.warning("Unknown artifact type %s, skipping", art_type_str)
            continue

        artifact = Artifact(
            id=art_data["id"],
            project_id=project_id,
            artifact_type=art_type,
            name=art_data.get("name", art_type_str),
            component_key=art_data.get("component_key"),
            content=content,
            status=ArtifactStatus.AWAITING_REVIEW,
            file_path=file_path,
            version=art_data.get("version", 1),
            git_commit_sha=art_data.get("git_commit_sha"),
        )
        db.merge(artifact)
        artifact_count += 1
        snapshot_artifact_statuses[art_data["id"]] = "awaiting_review"

    # ── Step 4: Recreate component definitions ────────────────────────
    comp_count = 0
    for comp_data in state.get("component_definitions", []):
        comp = ComponentDefinition(
            project_id=project_id,
            key=comp_data["key"],
            name=comp_data.get("name", comp_data["key"]),
            parent_key=comp_data.get("parent_key"),
            dependencies=comp_data.get("dependencies", []),
        )
        db.merge(comp)
        comp_count += 1

    # ── Step 5: Create fresh snapshot ─────────────────────────────────
    snapshot = PipelineSnapshot(
        project_id=project_id,
        last_sequence=0,
        run_status={},
        stage_statuses={},
        artifact_statuses=snapshot_artifact_statuses,
        is_running=False,
        is_paused=False,
        paused_stage=None,
        current_run_id=None,
    )
    db.add(snapshot)

    # ── Step 6: Emit pipeline_reset event ─────────────────────────────
    from backend.pipeline.event_store import EventStore

    es = EventStore(db)
    es.emit(project_id, "pipeline_reset", {
        "reconstructed_from": ref,
        "artifact_count": artifact_count,
        "component_count": comp_count,
    })

    db.commit()

    summary = {
        "project_id": project_id,
        "commit": ref,
        "run_number": state.get("run_number"),
        "artifacts_restored": artifact_count,
        "components_restored": comp_count,
        "status": "All artifacts set to AWAITING_REVIEW",
    }
    logger.info("Reconstruction complete: %s", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Reconstruct pipeline state from git repository"
    )
    parser.add_argument("project_id", help="Project ID to reconstruct")
    parser.add_argument(
        "--commit",
        default=None,
        help="Git commit SHA to reconstruct from (default: HEAD)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    db = SessionLocal()
    try:
        result = reconstruct_from_git(db, args.project_id, args.commit)
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Reconstruction failed: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
