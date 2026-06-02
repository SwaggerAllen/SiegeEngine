"""Single-feature LLM expansion handler.

Registered on the pipeline job queue as ``v2.expand_single_feature``.
Enqueued by ``apply_instruction._apply_propose_feature`` when a
``ProposeFeature`` instruction lands. The instruction's apply step
mints the structural slot (``NodeCreated`` with ``name=name_hint`` and
empty content) immediately for UI feedback and enqueues this handler
to fill in the canonical name + intent paragraph.

Flow:

1. Re-fetch the source ``PendingInstruction`` row. If it's no longer
   ``running`` (someone discarded it), emit ``NodeDeleted`` for
   rollback and exit without flipping status (it's already terminal).
2. Re-fetch the feat node. If it's missing or already has non-empty
   content, exit (idempotency — a re-run after a worker crash sees
   completed work and bails).
3. Read the project input doc + existing feature list for prompt
   context.
4. Render the prompt and call the CLI.
5. **On success:** parse the output as a single ``<feature>`` block,
   emit ``NodeRenamed`` (if the canonical name differs from the
   placeholder), ``NodeContentUpdated`` (intent paragraph), and an
   ``EdgeCreated`` for the feat→reqs decomposition edge if a reqs
   node exists. Flip the source row to ``applied``.
6. **On failure** (CLI error, parse-validate error): emit
   ``NodeDeleted`` (clean rollback — the empty feat goes away),
   flip the source row to ``failed`` with the error.
7. **Discarded mid-flight:** if the source row was discarded while
   the LLM was running, still emit ``NodeDeleted`` (rollback) but
   skip the status flip (already terminal) and skip the batch-
   completion check (discarded rows don't participate).
8. **Batch completion:** after the row flip, query the source row's
   ``job_id`` for sibling rows still in ``running`` (with
   ``FOR UPDATE`` to serialize concurrent expansion handlers'
   completion checks). If zero, call ``flush_pending_regens`` to
   enqueue downstream regens — exactly one cascade per apply-batch.

Failures during the network / parse path are wrapped to never leave
the projection in a half-state: either the feat lands fully expanded
with its edges, or it disappears entirely.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.cli.manager import cli_manager
from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import ValidationError, validate_features
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.prompts.expand_single_feature import (
    format_existing_features_summary,
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.reducer import append_event
from backend.models.input_document import InputDocument
from backend.models.node import Node
from backend.models.pending_instruction import PendingInstruction
from backend.pipeline import queue as pipeline_queue


def get_reqs_node(session, project_id: str) -> Node | None:
    """Inlined from backend.graph.requirements (now deleted)."""
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "reqs",
        )
    ).scalar_one_or_none()


logger = logging.getLogger(__name__)

EXPAND_SINGLE_FEATURE_JOB_TYPE = "v2.expand_single_feature"


class ExpandSingleFeatureError(RuntimeError):
    """Raised when the expansion can't proceed (bad payload, etc.)."""


async def _handle(payload: dict) -> None:
    project_id = payload.get("project_id")
    feat_node_id = payload.get("feat_node_id")
    description = payload.get("description")
    source_row_id = payload.get("source_pending_instruction_id")
    if not all(isinstance(v, str) and v for v in (project_id, feat_node_id, description)):
        raise ExpandSingleFeatureError(
            "v2.expand_single_feature payload missing project_id/feat_node_id/description"
        )
    if not isinstance(source_row_id, str) or not source_row_id:
        raise ExpandSingleFeatureError(
            "v2.expand_single_feature payload missing source_pending_instruction_id"
        )
    assert isinstance(project_id, str)
    assert isinstance(feat_node_id, str)
    assert isinstance(description, str)
    assert isinstance(source_row_id, str)

    db = SessionLocal()
    try:
        # ── Idempotency / discard guards ──────────────────────────────
        source_row = db.get(PendingInstruction, source_row_id)
        if source_row is None:
            logger.warning(
                "v2.expand_single_feature: source row %s not found — skipping",
                source_row_id,
            )
            return

        feat = db.get(Node, feat_node_id)
        if feat is None or feat.project_id != project_id:
            # Node already deleted (e.g. concurrent rollback) — exit.
            logger.warning(
                "v2.expand_single_feature: feat %s not found in project %s — skipping",
                feat_node_id,
                project_id,
            )
            return

        if source_row.status == "discarded":
            # User discarded the propose while expansion was in flight.
            # Still roll back the empty feat node, but don't touch the
            # row's status (already terminal) and don't participate in
            # batch-completion cascade.
            logger.info(
                "v2.expand_single_feature: source row %s discarded — rolling back feat %s",
                source_row_id,
                feat_node_id,
            )
            append_event(db, project_id, ev.NodeDeleted(node_id=feat_node_id))
            commit_and_publish(db, project_id)
            return

        if source_row.status != "running":
            # Already applied / failed (worker re-run after crash).
            # Exit without re-emitting events.
            logger.info(
                "v2.expand_single_feature: source row %s status=%s (not running) — skipping",
                source_row_id,
                source_row.status,
            )
            return

        if feat.content and feat.content.strip():
            # Idempotency: feat already has content from a prior run.
            # Just flip the row if it's still running and check batch.
            logger.info(
                "v2.expand_single_feature: feat %s already has content — flipping row only",
                feat_node_id,
            )
            source_row.status = "applied"
            source_row.error = None
            source_row.updated_at = datetime.utcnow()
            commit_and_publish(db, project_id)
            _check_batch_and_flush(db, project_id, source_row.job_id)
            return

        # ── Gather prompt context ─────────────────────────────────────
        input_doc_row = (
            db.query(InputDocument)
            .filter(
                InputDocument.project_id == project_id,
                InputDocument.doc_type == "project_doc",
            )
            .order_by(InputDocument.created_at.desc())
            .first()
        )
        input_doc = input_doc_row.content if input_doc_row else ""

        existing_feats = (
            db.query(Node)
            .filter(
                Node.project_id == project_id,
                Node.tier == "feat",
                Node.id != feat_node_id,
            )
            .order_by(Node.display_order, Node.created_at)
            .all()
        )
        existing_summary = format_existing_features_summary(
            [
                {
                    "name": f.name,
                    "content": f.content,
                    "group_label": f.group_label,
                }
                for f in existing_feats
            ]
        )

        name_hint = feat.name

        # ── Call LLM ──────────────────────────────────────────────────
        try:
            user_prompt = render_user_prompt(
                input_doc=input_doc,
                existing_features_summary=existing_summary,
                name_hint=name_hint,
                description=description,
            )
            result = await cli_manager.generate_with_usage(
                prompt=user_prompt,
                system_prompt=render_system_prompt(),
            )
            tree = extract_tag_tree(result.text, "features")
            features = validate_features(tree)
        except (ParseError, ValidationError, Exception) as exc:  # noqa: BLE001
            # Any failure on the LLM/parse path → roll back the empty
            # feat. Re-fetch the row in case it was discarded
            # between our earlier check and now.
            logger.warning(
                "v2.expand_single_feature: feat %s expansion failed: %s",
                feat_node_id,
                exc,
            )
            db.rollback()
            source_row = db.get(PendingInstruction, source_row_id)
            assert source_row is not None
            now = datetime.utcnow()
            append_event(db, project_id, ev.NodeDeleted(node_id=feat_node_id))
            if source_row.status == "running":
                source_row.status = "failed"
                source_row.error = str(exc)[:1000]
                source_row.updated_at = now
                commit_and_publish(db, project_id)
                _check_batch_and_flush(db, project_id, source_row.job_id)
            else:
                # Already discarded / terminal — just commit the
                # rollback delete and skip batch logic.
                commit_and_publish(db, project_id)
            return

        if len(features) != 1:
            # Multi-feature output is a prompt violation — treat as
            # failure, roll back.
            err = (
                f"Expected exactly 1 <feature> in expansion output, got {len(features)}. "
                "The prompt asks for one feature; this is a prompt-compliance bug."
            )
            logger.warning("v2.expand_single_feature: feat %s — %s", feat_node_id, err)
            db.rollback()
            source_row = db.get(PendingInstruction, source_row_id)
            assert source_row is not None
            now = datetime.utcnow()
            append_event(db, project_id, ev.NodeDeleted(node_id=feat_node_id))
            if source_row.status == "running":
                source_row.status = "failed"
                source_row.error = err
                source_row.updated_at = now
                commit_and_publish(db, project_id)
                _check_batch_and_flush(db, project_id, source_row.job_id)
            else:
                commit_and_publish(db, project_id)
            return

        canonical = features[0]

        # ── Re-check discard before committing success ────────────────
        # Expire the identity map so a cross-session discard committed
        # while the LLM call was in flight is visible. Without this,
        # ``db.get`` returns the cached row whose ``status`` is still
        # ``running`` from the initial fetch.
        db.expire_all()
        source_row = db.get(PendingInstruction, source_row_id)
        assert source_row is not None
        if source_row.status == "discarded":
            # User discarded while LLM was running — still roll back.
            logger.info(
                "v2.expand_single_feature: source row %s discarded mid-flight — rolling back",
                source_row_id,
            )
            append_event(db, project_id, ev.NodeDeleted(node_id=feat_node_id))
            commit_and_publish(db, project_id)
            return

        # ── Emit success events + flip row + check batch ──────────────
        if canonical.name.strip() != feat.name.strip():
            append_event(
                db,
                project_id,
                ev.NodeRenamed(node_id=feat_node_id, new_name=canonical.name.strip()),
            )
        append_event(
            db,
            project_id,
            ev.NodeContentUpdated(node_id=feat_node_id, new_content=canonical.intent.strip()),
        )

        # Mint feat→reqs decomposition edge so downstream cascade has
        # something to walk. Only mint if reqs node exists; if not,
        # the existing reqs_mint will mint edges for all current feats
        # at the next reqs approval (covers projects where reqs hasn't
        # bootstrapped yet).
        reqs_node = get_reqs_node(db, project_id)
        if reqs_node is not None:
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="decomposition",
                    source_id=feat_node_id,
                    target_id=reqs_node.id,
                ),
            )

        now = datetime.utcnow()
        source_row.status = "applied"
        source_row.error = None
        source_row.updated_at = now
        commit_and_publish(db, project_id)

        _check_batch_and_flush(db, project_id, source_row.job_id)
    finally:
        db.close()


def _check_batch_and_flush(db: Session, project_id: str, job_id: str | None) -> None:
    """If no sibling rows in ``job_id`` are still running, flush regens.

    Uses ``SELECT ... FOR UPDATE`` to serialize concurrent expansion
    handlers' completion checks so only one of them sees "I'm the
    last" and fires the consolidated cascade.
    """
    if job_id is None:
        # Defensive — the queue handler always assigns job_id on
        # apply, but if somehow it's None just call flush directly.
        from backend.graph.fanout import flush_pending_regens

        for job_type, payload in flush_pending_regens(db, project_id):
            pipeline_queue.enqueue(db, job_type=job_type, payload=payload)
        db.commit()
        return

    # FOR UPDATE on sibling running rows in the batch — serializes
    # completion checks so only one handler fires the cascade.
    still_running = (
        db.execute(
            select(PendingInstruction.id)
            .where(
                PendingInstruction.project_id == project_id,
                PendingInstruction.job_id == job_id,
                PendingInstruction.status == "running",
            )
            .with_for_update()
        )
        .scalars()
        .all()
    )
    if still_running:
        # Other expansions in the batch haven't finished — they'll
        # fire the cascade when the last one lands.
        db.commit()
        return

    from backend.graph.fanout import flush_pending_regens

    for job_type, payload in flush_pending_regens(db, project_id):
        pipeline_queue.enqueue(db, job_type=job_type, payload=payload)
    db.commit()


def register() -> None:
    """Register the expand_single_feature handler with the pipeline queue."""
    pipeline_queue.register_handler(EXPAND_SINGLE_FEATURE_JOB_TYPE, _handle)
