"""Project debug snapshot — single-shot read of every projection
table + the recent event tail + the (now frozen) job log.

Designed to be the "copy this to a paste buffer" debugging tool:
when something goes wrong (a draft state mismatch, an unexpected
projection row), the user can dump the full project state into a
JSON blob and either eyeball it or hand it back for diagnosis.

The recent_jobs tail surfaces pre-retirement Job rows (the
pipeline that wrote them is gone); useful for historical context
until the table itself drops in a follow-up migration.

Cost note: this endpoint reads every node + edge + draft + recent
events + recent jobs in a single transaction. For large projects
the response may be sizable (multiple MB). It's intentionally
ungated by pagination — the whole point is "see everything at
once". If a project ever grows beyond what fits in a single
response, paginate then.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.models import Project, User
from backend.models.graph_event import GraphEvent
from backend.models.job import Job
from backend.models.node import Draft, Edge, Fragment, Node, StalenessLedger

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/debug/snapshot")
def get_debug_snapshot(
    project_id: str,
    events: int = 200,
    jobs: int = 100,
    staleness: int = 200,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Dump the project's full state plus the most recent events
    and (now frozen) jobs as a single JSON blob.

    Query parameters:

    - ``events`` — number of trailing GraphEvent rows to include
      (default 200). Capped at 2000.
    - ``jobs`` — number of trailing Job rows to include (default
      100). Capped at 500. Rows are pre-retirement only — no new
      jobs land server-side.
    - ``staleness`` — number of StalenessLedger rows to include
      (default 200). Capped at 2000. Without a cap, a project with
      a large stale set can balloon the response past what the
      debug panel can copy to the clipboard.
    """
    project = _require_project(db, project_id)
    events_limit = max(0, min(events, 2000))
    jobs_limit = max(0, min(jobs, 500))
    staleness_limit = max(0, min(staleness, 2000))

    nodes = list(
        db.execute(
            select(Node)
            .where(Node.project_id == project_id)
            .order_by(Node.tier.asc(), Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )
    edges = list(
        db.execute(
            select(Edge).where(Edge.project_id == project_id).order_by(Edge.id.asc())
        ).scalars()
    )
    fragments = list(
        db.execute(
            select(Fragment)
            .where(Fragment.project_id == project_id)
            .order_by(Fragment.owner_id.asc(), Fragment.fragment_kind.asc())
        ).scalars()
    )
    drafts = list(
        db.execute(
            select(Draft)
            .where(Draft.project_id == project_id)
            .order_by(desc(Draft.created_at))
            .limit(200)
        ).scalars()
    )
    ledger_rows = list(
        db.execute(
            select(StalenessLedger)
            .where(StalenessLedger.project_id == project_id)
            .order_by(StalenessLedger.stale_node_id.asc())
            .limit(staleness_limit)
        ).scalars()
    )
    recent_jobs = list(
        db.execute(
            select(Job)
            .where(Job.payload["project_id"].as_string() == project_id)
            .order_by(desc(Job.created_at))
            .limit(jobs_limit)
        ).scalars()
    )
    recent_events = list(
        db.execute(
            select(GraphEvent)
            .where(GraphEvent.project_id == project_id)
            .order_by(desc(GraphEvent.offset))
            .limit(events_limit)
        ).scalars()
    )

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "git_repo_path": project.git_repo_path,
            "created_at": project.created_at.isoformat() if project.created_at else None,
        },
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "fragment_count": len(fragments),
            "draft_count": len(drafts),
            "staleness_rows": len(ledger_rows),
            "jobs_returned": len(recent_jobs),
            "events_returned": len(recent_events),
        },
        "nodes": [
            {
                "id": n.id,
                "tier": n.tier,
                "kind": n.kind,
                "parent_id": n.parent_id,
                "name": n.name,
                "display_order": n.display_order,
                "is_foundation": getattr(n, "is_foundation", False),
                "is_deferred": getattr(n, "is_deferred", False),
                "group_label": getattr(n, "group_label", None),
                "is_implicit": getattr(n, "is_implicit", False),
                "content_length": len(n.content or ""),
                "review_text_length": len(getattr(n, "review_text", "") or ""),
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id,
                "edge_type": e.edge_type,
                "source_id": e.source_id,
                "target_id": e.target_id,
            }
            for e in edges
        ],
        "fragments": [
            {
                "id": f.id,
                "owner_id": f.owner_id,
                "fragment_kind": f.fragment_kind,
                "content_length": len(f.content or ""),
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in fragments
        ],
        "drafts": [
            {
                "id": d.id,
                "target_type": getattr(d, "target_type", None),
                "target_id": d.target_id,
                "status": d.status,
                "section": getattr(d, "section", None),
                "discard_reason": getattr(d, "discard_reason", None),
                "auto_revision_pass": getattr(d, "auto_revision_pass", None),
                "review_status": getattr(d, "review_status", None),
                "content_length": len(d.content or ""),
                "review_text_length": len(getattr(d, "review_text", "") or ""),
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in drafts
        ],
        "staleness": [
            {
                "stale_node_id": r.stale_node_id,
                "source_node_id": r.source_node_id,
                "source_offset": r.source_offset,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in ledger_rows
        ],
        "recent_jobs": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "status": j.status,
                "priority": j.priority,
                "retry_count": j.retry_count,
                "max_retries": j.max_retries,
                "is_deferred": getattr(j, "is_deferred", False),
                "locked_by": j.locked_by,
                "error_message": j.error_message,
                "payload": _strip_payload_content(j.payload),
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in recent_jobs
        ],
        "recent_events": [
            {
                "id": e.id,
                "offset": e.offset,
                "event_type": e.event_type,
                "payload": _strip_payload_content(e.payload),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent_events
        ],
    }


# Payload fields that carry full document bodies, raw LLM output,
# or carried-forward review text — they bloat the copy-this-to-
# clipboard debug snapshot when left raw. Stripped when the
# snapshot serializes events and jobs; each is replaced with a
# short ``[content elided: N chars]`` placeholder so the
# surrounding causality (event_type, draft_id, node_id, offsets,
# timestamps, payload IDs) stays readable but the dump fits in a
# normal paste buffer.
#
# Covers:
# - ``content`` / ``new_content`` — event payloads carrying full
#   tier doc bodies (NodeCreated, NodeContentUpdated,
#   FragmentUpdated, DraftGenerated, FanInContentUpdated, etc.)
# - ``review_text`` — event payload carrying the full AI review
#   XML (DraftReviewUpdated)
# - ``prior_review_text`` — job payload field carried forward into
#   a regen so the LLM sees the previous review's findings; the
#   bulk offender on tier-ops Regen From Reviews queues
# - ``_failed_raw_output`` — job payload field saved by the
#   parse-validate retry loop on terminal failure for debugging;
#   raw LLM text, can be tens of KB
_ELIDED_PAYLOAD_FIELDS: frozenset[str] = frozenset(
    {
        "content",
        "new_content",
        "review_text",
        "prior_review_text",
        "_failed_raw_output",
    }
)


def _strip_payload_content(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return payload
    out: dict = {}
    for k, v in payload.items():
        if k in _ELIDED_PAYLOAD_FIELDS and isinstance(v, str) and len(v) > 200:
            out[k] = f"[content elided: {len(v)} chars]"
        else:
            out[k] = v
    return out
