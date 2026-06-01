"""Pipeline orchestration across the six stages.

Idempotency is the spine here:
  - messages dedupe on Message-ID (primary key, ON CONFLICT DO NOTHING semantics
    via existence checks),
  - threads carry a content fingerprint (sorted message-ids + last activity) so a
    thread is only re-summarized when it actually changed,
  - drafts refresh only when older than ``draft_metadata_refresh_days``.

Every stage is defensive: archive outages, malformed messages, and LLM errors
are logged to processing_log and skipped, never fatal.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .costs import estimate_cost, log_event, log_llm_call, total_spend
from .ingestion.archive import ArchiveUnavailable, Fetcher, fetch_list_mbox, iter_mbox_messages
from .ingestion.mail_parser import ParsedMessage, parse_message
from .ingestion.threads import reconstruct
from .llm import categorize, prefilter, summarize
from .llm.batch import BatchRequest, BatchRunner
from .logging_conf import get_logger
from .models import (
    ConsensusState,
    Draft,
    Message,
    ProcessingStage,
    Thread,
    ThreadDraft,
    ThreadStatus,
    ThreadTopic,
    Topic,
)
from .processing.clean import clean_body
from .processing.drafts import DatatrackerClient, extract_references, utcnow

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Topic seeding
# ---------------------------------------------------------------------------


def seed_topics(session: Session, settings: Settings | None = None) -> int:
    """Upsert the configured taxonomy into the topics table. Returns count."""
    settings = settings or get_settings()
    existing = {t.name: t for t in session.execute(select(Topic)).scalars().all()}
    for tcfg in settings.topics:
        row = existing.get(tcfg.name)
        if row is None:
            session.add(
                Topic(name=tcfg.name, description=tcfg.description, keywords=list(tcfg.keywords))
            )
        else:
            row.description = tcfg.description
            row.keywords = list(tcfg.keywords)
    session.flush()
    return len(settings.topics)


# ---------------------------------------------------------------------------
# Stage 1+: ingestion
# ---------------------------------------------------------------------------


def _thread_fingerprint(messages: list[Message]) -> str:
    ids = sorted(m.message_id for m in messages)
    last = max((m.date for m in messages if m.date), default=None)
    payload = "|".join(ids) + "#" + (last.isoformat() if last else "")
    return hashlib.sha1(payload.encode()).hexdigest()


def ingest_working_group(
    session: Session,
    working_group: str,
    *,
    since_iso: str | None = None,
    fetcher: Fetcher | None = None,
    raw_mbox: bytes | None = None,
) -> dict:
    """Fetch + parse + store raw messages and (re)build threads for one WG.

    ``raw_mbox`` lets callers (and tests) skip the network and pass mbox bytes
    directly. Returns counts for reporting.
    """
    settings = get_settings()
    if raw_mbox is None:
        owns = fetcher is None
        fetcher = fetcher or Fetcher().__enter__()
        try:
            raw_mbox = fetch_list_mbox(working_group, since_iso, fetcher)
        except ArchiveUnavailable as exc:
            log_event(
                session,
                stage=ProcessingStage.ingestion,
                status="error",
                working_group=working_group,
                detail={"error": str(exc)},
            )
            log.error("archive unavailable", extra={"wg": working_group, "error": str(exc)})
            return {"working_group": working_group, "ingested": 0, "error": str(exc)}
        finally:
            if owns and fetcher is not None:
                fetcher.__exit__(None, None, None)

    parsed: list[ParsedMessage] = []
    for email_msg in iter_mbox_messages(raw_mbox):
        pm = parse_message(email_msg)
        if pm is not None:
            parsed.append(pm)

    new_count = 0
    for pm in parsed:
        if session.get(Message, pm.message_id) is not None:
            continue  # dedupe by Message-ID
        session.add(
            Message(
                message_id=pm.message_id,
                thread_id=None,  # assigned during reconstruction below
                working_group=working_group,
                from_address=pm.from_address,
                from_name=pm.from_name,
                subject=pm.subject,
                date=pm.date,
                archive_url=pm.archive_url,
                body_original=pm.body_original,
                body_cleaned=clean_body(pm.body_original),
                in_reply_to=pm.in_reply_to,
                references=pm.references,
            )
        )
        new_count += 1
    session.flush()

    # Rebuild threads over the *entire* WG message set (cheap, keeps grouping
    # stable as late replies arrive). Reconstruction is deterministic.
    all_msgs = session.execute(
        select(Message).where(Message.working_group == working_group)
    ).scalars().all()
    parsed_all = [
        ParsedMessage(
            message_id=m.message_id,
            from_address=m.from_address,
            from_name=m.from_name,
            subject=m.subject,
            date=m.date,
            archive_url=m.archive_url,
            in_reply_to=m.in_reply_to,
            references=m.references or [],
            body_original=m.body_original or "",
        )
        for m in all_msgs
    ]
    threads = reconstruct(parsed_all, working_group)
    msg_by_id = {m.message_id: m for m in all_msgs}
    active_threshold = timedelta(days=settings.processing.active_threshold_days)
    now = datetime.now(UTC)

    for rt in threads:
        members = [msg_by_id[m.message_id] for m in rt.messages]
        root = min(members, key=lambda m: (m.date is None, m.date))
        last = max((m.date for m in members if m.date), default=root.date)
        participants = sorted({m.from_address for m in members if m.from_address})

        thread = session.get(Thread, rt.thread_id)
        heuristic_status = (
            ThreadStatus.concluded
            if last and (now - last) > active_threshold
            else ThreadStatus.active
        )
        if thread is None:
            thread = Thread(thread_id=rt.thread_id)
            session.add(thread)
            thread.status = heuristic_status
        thread.subject = root.subject or "(no subject)"
        thread.working_group = working_group
        thread.start_date = root.date
        thread.last_activity_date = last
        thread.message_count = len(members)
        thread.archive_url = root.archive_url
        thread.participants = participants
        # Only the heuristic touches status here; a later LLM status (abandoned)
        # set during summarization is preserved unless the thread looks active again.
        if thread.status != ThreadStatus.abandoned:
            thread.status = heuristic_status
        # Flush the thread row before pointing messages at it (FK ordering).
        session.flush()
        for m in members:
            m.thread_id = rt.thread_id

    session.flush()
    log_event(
        session,
        stage=ProcessingStage.ingestion,
        status="ok",
        working_group=working_group,
        detail={"new_messages": new_count, "threads": len(threads)},
    )
    return {"working_group": working_group, "ingested": new_count, "threads": len(threads)}


# ---------------------------------------------------------------------------
# Stage 3: draft extraction + metadata sync
# ---------------------------------------------------------------------------


def sync_drafts(
    session: Session,
    *,
    working_group: str | None = None,
    client: DatatrackerClient | None = None,
) -> dict:
    """Extract draft references from messages, ensure Draft rows, link thread_drafts."""
    settings = get_settings()
    refresh_after = timedelta(days=settings.processing.draft_metadata_refresh_days)
    now = utcnow()

    q = select(Message)
    if working_group:
        q = q.where(Message.working_group == working_group)
    messages = session.execute(q).scalars().all()

    # thread_id -> {draft_name -> (versions set, earliest date)}
    thread_refs: dict[str, dict[str, tuple[set[str], datetime | None]]] = {}
    draft_names: set[str] = set()
    for m in messages:
        if not m.thread_id:
            continue
        refs = extract_references(m.body_original or m.body_cleaned or "")
        for base, ref in refs.items():
            draft_names.add(base)
            bucket = thread_refs.setdefault(m.thread_id, {})
            versions, earliest = bucket.get(base, (set(), None))
            versions |= ref.versions
            if m.date and (earliest is None or m.date < earliest):
                earliest = m.date
            bucket[base] = (versions, earliest)

    owns = client is None
    client = client or DatatrackerClient().__enter__()
    synced = 0
    try:
        for name in sorted(draft_names):
            existing = session.get(Draft, name)
            stale = existing is not None and (
                existing.last_checked is None or (now - existing.last_checked) > refresh_after
            )
            if existing is None and settings.drafts.fetch_metadata_on_first_reference:
                meta = client.fetch_draft(name)
                _upsert_draft(session, name, meta, now, first_seen=True)
                synced += 1
            elif existing is None:
                _upsert_draft(session, name, None, now, first_seen=True)
            elif stale:
                meta = client.fetch_draft(name)
                _upsert_draft(session, name, meta, now, first_seen=False)
                synced += 1
    finally:
        if owns:
            client.__exit__(None, None, None)

    session.flush()

    # Link thread_drafts.
    links = 0
    for thread_id, bucket in thread_refs.items():
        for name, (versions, earliest) in bucket.items():
            link = session.get(ThreadDraft, {"thread_id": thread_id, "draft_name": name})
            if link is None:
                link = ThreadDraft(thread_id=thread_id, draft_name=name)
                session.add(link)
                links += 1
            link.versions_referenced = sorted(versions) if versions else None
            link.first_referenced_in_thread = earliest
    session.flush()
    log_event(
        session,
        stage=ProcessingStage.draft_sync,
        status="ok",
        working_group=working_group,
        detail={"drafts_synced": synced, "links": links},
    )
    return {"drafts": len(draft_names), "synced": synced, "links": links}


def _upsert_draft(session: Session, name, meta, now, *, first_seen: bool) -> None:
    d = session.get(Draft, name)
    if d is None:
        d = Draft(draft_name=name, first_seen=now)
        session.add(d)
    d.last_checked = now
    if meta is not None:
        d.title = meta.title or d.title
        d.current_version = meta.current_version or d.current_version
        d.working_group = meta.working_group or d.working_group
        d.status = meta.status or d.status
        d.rfc_number = meta.rfc_number or d.rfc_number
        d.authors = meta.authors or d.authors
        d.abstract = meta.abstract or d.abstract
        d.datatracker_url = meta.datatracker_url or d.datatracker_url
        if meta.versions:
            d.versions = meta.versions


# ---------------------------------------------------------------------------
# Budget guard
# ---------------------------------------------------------------------------


class BudgetExceeded(RuntimeError):
    pass


def _check_budget(session: Session, projected: float, force: bool) -> None:
    budget = get_settings().processing.budget_usd
    spent = total_spend(session)
    if not force and (spent + projected) > budget:
        raise BudgetExceeded(
            f"Projected spend ${spent + projected:.2f} exceeds budget ${budget:.2f} "
            f"(already spent ${spent:.2f}). Re-run with force=True to override."
        )


# ---------------------------------------------------------------------------
# Stage 2 (LLM): admin prefilter
# ---------------------------------------------------------------------------


def run_prefilter(
    session: Session,
    *,
    working_group: str | None = None,
    runner: BatchRunner | None = None,
    force: bool = False,
) -> dict:
    if not get_settings().processing.pre_filter_admin_messages:
        return {"skipped": "pre_filter_admin_messages disabled"}
    q = select(Message).where(Message.is_admin.is_(None))
    if working_group:
        q = q.where(Message.working_group == working_group)
    messages = session.execute(q).scalars().all()
    if not messages:
        return {"classified": 0}

    model = get_settings().llm.model_categorization
    # Rough projection: ~1.2k input + 30 output tokens per message.
    projected = estimate_cost(model, 1200 * len(messages), 30 * len(messages), batch=True)
    _check_budget(session, projected, force)

    reqs = [
        prefilter.build_request(m.message_id, m.subject, m.body_cleaned or "", model)
        for m in messages
    ]
    results = _dispatch(reqs, runner)
    by_id = {m.message_id: m for m in messages}
    classified = 0
    for cid, res in results.items():
        msg_id = cid.split("::", 1)[1]
        msg = by_id.get(msg_id)
        if msg is None:
            continue
        if res.succeeded:
            msg.is_admin = prefilter.parse_result(res.text)
            classified += 1
            log_llm_call(
                session,
                stage=ProcessingStage.prefilter,
                model=model,
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
                batch=True,
                working_group=msg.working_group,
                target_id=msg_id,
            )
        else:
            msg.is_admin = False  # fail open: keep the message
            log_llm_call(
                session,
                stage=ProcessingStage.prefilter,
                model=model,
                input_tokens=0,
                output_tokens=0,
                batch=True,
                target_id=msg_id,
                status="error",
                detail={"error": res.error},
            )
    session.flush()
    return {"classified": classified}


# ---------------------------------------------------------------------------
# Stage 4: summarization
# ---------------------------------------------------------------------------


def _threads_needing_summary(session: Session, working_group: str | None) -> list[Thread]:
    q = select(Thread)
    if working_group:
        q = q.where(Thread.working_group == working_group)
    out = []
    for t in session.execute(q).scalars().all():
        members = [m for m in t.messages if not m.is_admin]
        if not members:
            continue  # admin-only thread; skip summarization
        fp = _thread_fingerprint(members)
        if t.summary is None or t.summary_source_fingerprint != fp:
            out.append(t)
    return out


def run_summarization(
    session: Session,
    *,
    working_group: str | None = None,
    runner: BatchRunner | None = None,
    force: bool = False,
) -> dict:
    threads = _threads_needing_summary(session, working_group)
    if not threads:
        return {"summarized": 0}
    model = get_settings().llm.model_summarization

    reqs: list[BatchRequest] = []
    ctx: dict[str, Thread] = {}
    for t in threads:
        members = sorted(
            [m for m in t.messages if not m.is_admin],
            key=lambda m: (m.date is None, m.date),
        )
        msgs = [
            {
                "from_name": m.from_name,
                "from_address": m.from_address,
                "date": m.date.isoformat() if m.date else None,
                "body_cleaned": m.body_cleaned,
            }
            for m in members
        ]
        drafts = [
            {
                "draft_name": d.draft.draft_name,
                "title": d.draft.title,
                "current_version": d.draft.current_version,
                "abstract": d.draft.abstract,
            }
            for d in t.draft_links
        ]
        reqs.append(
            summarize.build_request(t.thread_id, t.subject, t.working_group, msgs, drafts, model)
        )
        ctx[t.thread_id] = t

    # Project ~ sum of message chars/4 input tokens + 800 output per thread.
    est_input = sum(
        len(m.body_cleaned or "") for t in threads for m in t.messages if not m.is_admin
    ) // 4
    projected = estimate_cost(model, est_input, 800 * len(threads), batch=True)
    _check_budget(session, projected, force)

    results = _dispatch(reqs, runner)
    summarized = 0
    for cid, res in results.items():
        tid = cid.split("::", 1)[1]
        t = ctx.get(tid)
        if t is None:
            continue
        if not res.succeeded:
            log_llm_call(
                session,
                stage=ProcessingStage.summarization,
                model=model,
                input_tokens=0,
                output_tokens=0,
                batch=True,
                working_group=t.working_group,
                target_id=tid,
                status="error",
                detail={"error": res.error},
            )
            continue
        parsed = summarize.parse_result(res.text)
        if parsed is None:
            log_llm_call(
                session,
                stage=ProcessingStage.summarization,
                model=model,
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
                batch=True,
                working_group=t.working_group,
                target_id=tid,
                status="error",
                detail={"error": "unparseable summary JSON"},
            )
            continue
        t.summary = parsed.summary
        t.key_positions = parsed.key_positions
        t.consensus_state = ConsensusState(parsed.consensus_state)
        # LLM status can mark a thread abandoned/concluded; otherwise keep heuristic.
        if parsed.status in (ThreadStatus.abandoned.value, ThreadStatus.concluded.value):
            t.status = ThreadStatus(parsed.status)
        members = [m for m in t.messages if not m.is_admin]
        t.summary_source_fingerprint = _thread_fingerprint(members)
        t.last_processed = datetime.now(UTC)
        summarized += 1
        log_llm_call(
            session,
            stage=ProcessingStage.summarization,
            model=model,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            batch=True,
            working_group=t.working_group,
            target_id=tid,
        )
    session.flush()
    return {"summarized": summarized}


# ---------------------------------------------------------------------------
# Stage 5: categorization
# ---------------------------------------------------------------------------


def run_categorization(
    session: Session,
    *,
    working_group: str | None = None,
    runner: BatchRunner | None = None,
    only_uncategorized: bool = True,
    force: bool = False,
) -> dict:
    topics = session.execute(select(Topic)).scalars().all()
    topic_id_by_name = {t.name: t.topic_id for t in topics}
    valid_names = set(topic_id_by_name)
    from .config import Topic as TopicCfg

    topic_cfgs = [
        TopicCfg(name=t.name, description=t.description or "", keywords=t.keywords or [])
        for t in topics
    ]

    q = select(Thread).where(Thread.summary.isnot(None))
    if working_group:
        q = q.where(Thread.working_group == working_group)
    threads = session.execute(q).scalars().all()
    if only_uncategorized:
        threads = [t for t in threads if not t.topic_links]
    if not threads:
        return {"categorized": 0}

    model = get_settings().llm.model_categorization
    reqs = []
    ctx = {}
    for t in threads:
        members = sorted(
            [m for m in t.messages if not m.is_admin], key=lambda m: (m.date is None, m.date)
        )[:3]
        sample = "\n".join((m.body_cleaned or "") for m in members)
        reqs.append(categorize.build_request(t.thread_id, t.summary or "", sample, topic_cfgs, model))
        ctx[t.thread_id] = t

    projected = estimate_cost(model, 2000 * len(threads), 150 * len(threads), batch=True)
    _check_budget(session, projected, force)

    results = _dispatch(reqs, runner)
    categorized = 0
    for cid, res in results.items():
        tid = cid.split("::", 1)[1]
        t = ctx.get(tid)
        if t is None or not res.succeeded:
            if t is not None:
                log_llm_call(
                    session,
                    stage=ProcessingStage.categorization,
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    batch=True,
                    working_group=t.working_group,
                    target_id=tid,
                    status="error",
                    detail={"error": res.error},
                )
            continue
        pairs = categorize.parse_result(res.text, valid_names)
        # Replace existing categorization for this thread.
        for link in list(t.topic_links):
            session.delete(link)
        session.flush()
        for name, conf in pairs:
            session.add(
                ThreadTopic(thread_id=tid, topic_id=topic_id_by_name[name], confidence=conf)
            )
        categorized += 1
        log_llm_call(
            session,
            stage=ProcessingStage.categorization,
            model=model,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            batch=True,
            working_group=t.working_group,
            target_id=tid,
        )
    session.flush()
    return {"categorized": categorized}


def recategorize_all(
    session: Session, *, runner: BatchRunner | None = None, force: bool = False
) -> dict:
    """Re-run categorization for every summarized thread against the current taxonomy.

    Cheap (Haiku, no re-summarization) — for use after the topic taxonomy changes.
    """
    seed_topics(session)
    return run_categorization(
        session, runner=runner, only_uncategorized=False, force=force
    )


# ---------------------------------------------------------------------------
# Dispatch helper
# ---------------------------------------------------------------------------


def _dispatch(reqs: list[BatchRequest], runner: BatchRunner | None):
    runner = runner or BatchRunner()
    batch_id = runner.submit(reqs)
    return runner.wait_and_collect(batch_id)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def run_full_pipeline(
    session: Session,
    *,
    working_groups: list[str] | None = None,
    since_iso: str | None = None,
    runner: BatchRunner | None = None,
    force: bool = False,
    skip_llm: bool = False,
) -> dict:
    """Run stages 1→5 end to end for the given (or all configured) working groups."""
    settings = get_settings()
    seed_topics(session, settings)
    wgs = working_groups or [w.name for w in settings.working_groups]
    report: dict = {"working_groups": {}}
    for wg in wgs:
        report["working_groups"][wg] = ingest_working_group(session, wg, since_iso=since_iso)
        report["working_groups"][wg]["drafts"] = sync_drafts(session, working_group=wg)
    if not skip_llm:
        report["prefilter"] = run_prefilter(session, runner=runner, force=force)
        report["summarization"] = run_summarization(session, runner=runner, force=force)
        report["categorization"] = run_categorization(session, runner=runner, force=force)
    report["total_spend_usd"] = round(total_spend(session), 4)
    return report
