"""Shared, presentation-agnostic query functions.

Every function returns plain JSON-serializable dicts and ALWAYS includes the
source ``archive_url`` alongside summaries so callers (CLI, MCP, web) can render
one-click-verifiable citations. Used by the CLI, the MCP server, and the web UI
so query semantics never diverge between interfaces.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .models import (
    Draft,
    Message,
    Thread,
    ThreadDraft,
    ThreadStatus,
    ThreadTopic,
    Topic,
)


def _brief(summary: str | None, limit: int = 280) -> str:
    if not summary:
        return ""
    return summary if len(summary) <= limit else summary[: limit - 1].rstrip() + "…"


def _date_range(t: Thread) -> str:
    s = t.start_date.date().isoformat() if t.start_date else "?"
    e = t.last_activity_date.date().isoformat() if t.last_activity_date else "?"
    return f"{s} → {e}"


def _thread_summary_row(t: Thread) -> dict:
    return {
        "thread_id": t.thread_id,
        "subject": t.subject,
        "working_group": t.working_group,
        "date_range": _date_range(t),
        "last_activity_date": t.last_activity_date.isoformat() if t.last_activity_date else None,
        "message_count": t.message_count,
        "status": t.status.value if t.status else None,
        "consensus_state": t.consensus_state.value if t.consensus_state else None,
        "summary_brief": _brief(t.summary),
        "archive_url": t.archive_url,
    }


def _topic_id(session: Session, topic_name: str) -> int | None:
    return session.execute(
        select(Topic.topic_id).where(Topic.name == topic_name)
    ).scalar_one_or_none()


def list_threads(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    stmt = select(Thread)
    conds = []
    if working_group:
        conds.append(Thread.working_group == working_group)
    if since:
        conds.append(Thread.last_activity_date >= since)
    if until:
        conds.append(Thread.last_activity_date <= until)
    if status:
        conds.append(Thread.status == ThreadStatus(status))
    if topic:
        tid = _topic_id(session, topic)
        if tid is None:
            return []
        stmt = stmt.join(ThreadTopic, ThreadTopic.thread_id == Thread.thread_id).where(
            ThreadTopic.topic_id == tid
        )
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(Thread.last_activity_date.desc().nullslast()).limit(limit)
    return [_thread_summary_row(t) for t in session.execute(stmt).scalars().all()]


def get_thread_detail(session: Session, thread_id: str) -> dict | None:
    t = session.get(Thread, thread_id)
    if t is None:
        return None
    topics = session.execute(
        select(Topic.name, ThreadTopic.confidence)
        .join(ThreadTopic, ThreadTopic.topic_id == Topic.topic_id)
        .where(ThreadTopic.thread_id == thread_id)
        .order_by(ThreadTopic.confidence.desc())
    ).all()
    drafts = session.execute(
        select(Draft, ThreadDraft.versions_referenced)
        .join(ThreadDraft, ThreadDraft.draft_name == Draft.draft_name)
        .where(ThreadDraft.thread_id == thread_id)
    ).all()
    return {
        "thread_id": t.thread_id,
        "subject": t.subject,
        "working_group": t.working_group,
        "date_range": _date_range(t),
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "last_activity_date": t.last_activity_date.isoformat() if t.last_activity_date else None,
        "message_count": t.message_count,
        "status": t.status.value if t.status else None,
        "consensus_state": t.consensus_state.value if t.consensus_state else None,
        "summary": t.summary,
        "key_positions": t.key_positions or [],
        "participants": t.participants or [],
        "topics": [{"topic": name, "confidence": conf} for name, conf in topics],
        "referenced_drafts": [
            {
                "draft_name": d.draft_name,
                "title": d.title,
                "current_version": d.current_version,
                "status": d.status,
                "rfc_number": d.rfc_number,
                "versions_referenced": vers,
                "datatracker_url": d.datatracker_url,
            }
            for d, vers in drafts
        ],
        "archive_url": t.archive_url,
    }


def recent_activity(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    days: int = 30,
    limit: int = 100,
) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    return list_threads(
        session, topic=topic, working_group=working_group, since=since, limit=limit
    )


def participants(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Most active participants (by message count) in a topic / WG."""
    stmt = select(
        Message.from_address,
        func.max(Message.from_name),
        func.count(Message.message_id).label("n"),
    ).where(Message.from_address.isnot(None))
    if working_group:
        stmt = stmt.where(Message.working_group == working_group)
    if topic:
        tid = _topic_id(session, topic)
        if tid is None:
            return []
        stmt = stmt.join(ThreadTopic, ThreadTopic.thread_id == Message.thread_id).where(
            ThreadTopic.topic_id == tid
        )
    stmt = stmt.group_by(Message.from_address).order_by(func.count(Message.message_id).desc()).limit(limit)
    return [
        {"from_address": addr, "from_name": name, "message_count": int(n)}
        for addr, name, n in session.execute(stmt).all()
    ]


def topic_overview(
    session: Session, *, topic: str, working_group: str | None = None
) -> dict:
    tid = _topic_id(session, topic)
    if tid is None:
        return {"topic": topic, "exists": False}
    base = select(Thread).join(ThreadTopic, ThreadTopic.thread_id == Thread.thread_id).where(
        ThreadTopic.topic_id == tid
    )
    if working_group:
        base = base.where(Thread.working_group == working_group)
    threads = session.execute(base.order_by(Thread.last_activity_date.desc().nullslast())).scalars().all()

    by_consensus: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for t in threads:
        c = t.consensus_state.value if t.consensus_state else "unknown"
        by_consensus[c] = by_consensus.get(c, 0) + 1
        s = t.status.value if t.status else "unknown"
        by_status[s] = by_status.get(s, 0) + 1

    active = [t for t in threads if t.status == ThreadStatus.active]
    open_questions = [
        _thread_summary_row(t)
        for t in threads
        if t.consensus_state and t.consensus_state.value in ("active_debate", "no_consensus")
    ][:10]

    return {
        "topic": topic,
        "exists": True,
        "thread_count": len(threads),
        "active_thread_count": len(active),
        "by_consensus": by_consensus,
        "by_status": by_status,
        "active_threads": [_thread_summary_row(t) for t in active[:10]],
        "open_questions": open_questions,
    }


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def _draft_thread_count(session: Session, draft_name: str) -> int:
    return int(
        session.execute(
            select(func.count(ThreadDraft.thread_id)).where(ThreadDraft.draft_name == draft_name)
        ).scalar_one()
    )


def list_drafts(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    status: str | None = None,
    referenced_since: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    stmt = select(Draft)
    conds = []
    if working_group:
        conds.append(Draft.working_group == working_group)
    if status:
        conds.append(Draft.status.ilike(f"%{status}%"))
    # Joins for topic / referenced_since filters go through thread_drafts.
    needs_join = topic is not None or referenced_since is not None
    if needs_join:
        stmt = stmt.join(ThreadDraft, ThreadDraft.draft_name == Draft.draft_name)
        if referenced_since:
            stmt = stmt.where(ThreadDraft.first_referenced_in_thread >= referenced_since)
        if topic:
            tid = _topic_id(session, topic)
            if tid is None:
                return []
            stmt = stmt.join(
                ThreadTopic, ThreadTopic.thread_id == ThreadDraft.thread_id
            ).where(ThreadTopic.topic_id == tid)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.distinct().limit(limit)
    drafts = session.execute(stmt).scalars().all()
    rows = [
        {
            "draft_name": d.draft_name,
            "title": d.title,
            "status": d.status,
            "current_version": d.current_version,
            "rfc_number": d.rfc_number,
            "thread_count": _draft_thread_count(session, d.draft_name),
            "datatracker_url": d.datatracker_url,
        }
        for d in drafts
    ]
    rows.sort(key=lambda r: r["thread_count"], reverse=True)
    return rows


def get_draft(session: Session, draft_name: str) -> dict | None:
    d = session.get(Draft, draft_name)
    if d is None:
        return None
    links = session.execute(
        select(Thread, ThreadDraft.versions_referenced, ThreadDraft.first_referenced_in_thread)
        .join(ThreadDraft, ThreadDraft.thread_id == Thread.thread_id)
        .where(ThreadDraft.draft_name == draft_name)
        .order_by(ThreadDraft.first_referenced_in_thread.desc().nullslast())
    ).all()
    return {
        "draft_name": d.draft_name,
        "title": d.title,
        "current_version": d.current_version,
        "working_group": d.working_group,
        "status": d.status,
        "rfc_number": d.rfc_number,
        "authors": d.authors or [],
        "abstract": d.abstract,
        "datatracker_url": d.datatracker_url,
        "versions": d.versions or [],
        "threads": [
            {
                "thread_id": t.thread_id,
                "subject": t.subject,
                "working_group": t.working_group,
                "date_range": _date_range(t),
                "versions_referenced": vers,
                "first_referenced_in_thread": fr.isoformat() if fr else None,
                "summary_brief": _brief(t.summary),
                "archive_url": t.archive_url,
            }
            for t, vers, fr in links
        ],
    }


def draft_discussion_history(session: Session, draft_name: str) -> dict | None:
    detail = get_draft(session, draft_name)
    if detail is None:
        return None
    history = sorted(
        detail["threads"], key=lambda r: r["first_referenced_in_thread"] or ""
    )
    return {
        "draft_name": draft_name,
        "title": detail["title"],
        "current_version": detail["current_version"],
        "history": history,
    }


def search_threads_fts(session: Session, query: str, *, limit: int = 50) -> list[dict]:
    """Postgres full-text search over thread subject+summary."""
    ts_query = func.websearch_to_tsquery("english", query)
    stmt = (
        select(Thread)
        .where(Thread.search_vector.op("@@")(ts_query))
        .order_by(func.ts_rank(Thread.search_vector, ts_query).desc())
        .limit(limit)
    )
    return [_thread_summary_row(t) for t in session.execute(stmt).scalars().all()]
