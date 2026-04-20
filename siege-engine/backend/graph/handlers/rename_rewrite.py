"""Rename prose-rewrite handler.

Registered on the pipeline job queue as ``v2.rename_rewrite``.
Enqueued by the Phase 11 apply-instructions dispatcher when a
``Rename`` instruction lands — the dispatcher does NOT emit
``NodeRenamed`` inline, because the name is load-bearing for
downstream consumers' prose and a direct DB rename would leave
every mention of the old name behind in rendered artifacts.

Flow:

1. Load the renamed node.
2. Collect direct consumers: every node with an **outgoing**
   ``reference`` or ``dependency`` edge pointing at the renamed
   node. This is the edge-graph-constrained rewrite scope from
   the Phase 11 plan; no full project walk.
3. For the renamed node and each consumer, rewrite their
   ``Node.content`` and every owned ``Fragment.content`` by
   replacing word-boundaried occurrences of ``old_name`` with
   ``new_name``. Emit ``FragmentUpdated`` per changed fragment
   (``NodeCreated``-equivalent body-rewrite for node content
   is done in-place — ``NodeRenamed`` is the canonical name
   event; body rewrites for node content are out-of-band here
   and applied directly to ``Node.content`` inside the
   transaction, mirroring how the reducer's ``_apply_draft_approved``
   writes approved content onto a node).
4. Emit ``NodeRenamed`` last — after all fragment rewrites
   land so the rename and the prose updates flush in one commit.

**Failure policy:** if the rewrite encounters an unexpected
error on a consumer, the rename still commits — the user's
intent was clear, and a stale name in a consumer's prose is
less bad than a lost rename. The failed consumer is logged;
the user can re-trigger a targeted regen on it.

**Rewrite backend (D3):** the handler calls
:func:`backend.cli.manager.cli_manager.generate_with_usage` with
a per-document prompt (see
``backend.graph.prompts.rename_rewrite``) and writes the LLM's
reply back as the new content. If the LLM errors, the CLI is
unavailable, or the env variable
``SIEGE_DISABLE_LLM_RENAME_REWRITE=1`` is set (used by tests),
the handler falls back to a word-boundary regex substitution —
correct for simple single-word renames and deterministic for
tests.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.cli.manager import cli_manager
from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.fragments import FragmentKind
from backend.graph.prompts.rename_rewrite import (
    SYSTEM_PROMPT,
    render_rename_rewrite_prompt,
)
from backend.graph.reducer import append_event
from backend.models.node import Edge, Fragment, Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

RENAME_REWRITE_JOB_TYPE = "v2.rename_rewrite"


def _rewrite_text_regex(text: str, old_name: str, new_name: str) -> str:
    """Word-boundaried text replacement. Correct for simple
    single-word renames and used as the fallback when the LLM
    path is disabled or fails.
    """
    if not text:
        return text
    pattern = re.compile(rf"\b{re.escape(old_name)}\b")
    return pattern.sub(new_name, text)


def _llm_rename_rewrite_disabled() -> bool:
    """True when the LLM rewrite path is opt-out disabled.

    Tests set ``SIEGE_DISABLE_LLM_RENAME_REWRITE=1`` so the
    rewrite path stays deterministic and doesn't attempt a CLI
    subprocess call.
    """
    return bool(os.environ.get("SIEGE_DISABLE_LLM_RENAME_REWRITE"))


async def _rewrite_text_llm(text: str, old_name: str, new_name: str) -> str:
    """Call the CLI to rewrite prose; raise on failure.

    Caller wraps this in a try/except and falls back to the
    regex path if the CLI errors or the LLM output looks
    malformed.
    """
    user_prompt = render_rename_rewrite_prompt(old_name=old_name, new_name=new_name, text=text)
    result = await cli_manager.generate_with_usage(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
    )
    return result.text.strip()


async def _rewrite_text(text: str, old_name: str, new_name: str) -> str:
    """Rewrite ``text`` replacing references to ``old_name``.

    Default path: call the LLM via
    :func:`_rewrite_text_llm`. Fallback path: word-boundary
    regex substitution. The fallback triggers on:

    - empty input (no-op for both paths),
    - ``SIEGE_DISABLE_LLM_RENAME_REWRITE=1`` env var,
    - LLM call raising any exception,
    - LLM output looking degenerate (empty, or a single-line
      explanation that doesn't contain any of the original
      source text tokens — detected by a naive length check).

    A log warning lands on fallback so operators can spot
    problematic renames.

    Async because the LLM call is async and the handler is
    already running inside the pipeline worker's event loop.
    """
    if not text:
        return text
    if _llm_rename_rewrite_disabled():
        return _rewrite_text_regex(text, old_name, new_name)
    try:
        rewritten = await _rewrite_text_llm(text, old_name, new_name)
    except Exception:
        logger.warning(
            "rename_rewrite: LLM call failed, falling back to regex rewrite",
            exc_info=True,
        )
        return _rewrite_text_regex(text, old_name, new_name)
    if not rewritten or len(rewritten) < max(4, len(text) // 3):
        logger.warning(
            "rename_rewrite: LLM returned degenerate output (len=%d, input=%d); "
            "falling back to regex rewrite",
            len(rewritten),
            len(text),
        )
        return _rewrite_text_regex(text, old_name, new_name)
    return rewritten


async def _rewrite_node_and_fragments(
    db: Session,
    project_id: str,
    node: Node,
    old_name: str,
    new_name: str,
) -> None:
    """Rewrite a node's Node.content + every fragment it owns.

    Emits ``FragmentUpdated`` per changed fragment. Node.content
    is rewritten directly on the ORM row — ``NodeRenamed`` carries
    the name; body prose rewrites for the node itself are applied
    in the same transaction without a dedicated content event.
    """
    # In-place rewrite of Node.content. No event covers generic node
    # content rewrite; fragments carry their own events, but the
    # node body is a simple column update inside this transaction.
    if node.content:
        new_content = await _rewrite_text(node.content, old_name, new_name)
        if new_content != node.content:
            node.content = new_content
            node.updated_at = datetime.utcnow()

    # Fragments — each gets a FragmentUpdated if its content changes.
    fragments = db.execute(select(Fragment).where(Fragment.owner_id == node.id)).scalars().all()
    for frag in fragments:
        new_content = await _rewrite_text(frag.content or "", old_name, new_name)
        if new_content == frag.content:
            continue
        # FragmentUpdated.fragment_kind is a FragmentKind enum value.
        kind_str = frag.fragment_kind
        try:
            kind_enum = FragmentKind(kind_str)
        except ValueError:
            logger.warning(
                "rename_rewrite: skipping fragment %s with unknown kind %r",
                frag.id,
                kind_str,
            )
            continue
        append_event(
            db,
            project_id,
            ev.FragmentUpdated(
                fragment_id=frag.id,
                owner_id=frag.owner_id,
                fragment_kind=kind_enum,
                new_content=new_content,
            ),
        )


def _collect_consumers(db: Session, project_id: str, renamed_id: str) -> list[Node]:
    """Return nodes with an outgoing reference/dependency edge at ``renamed_id``.

    These are the direct consumers whose prose may reference the
    renamed entity by name. Scope per the Phase 11 plan — no full
    project walk.
    """
    source_ids = (
        db.execute(
            select(Edge.source_id)
            .where(
                Edge.project_id == project_id,
                Edge.edge_type.in_(("reference", "dependency")),
                Edge.target_id == renamed_id,
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    if not source_ids:
        return []
    return list(db.execute(select(Node).where(Node.id.in_(list(source_ids)))).scalars())


async def _handle(payload: dict) -> None:
    project_id = payload.get("project_id")
    node_id = payload.get("node_id")
    old_name = payload.get("old_name")
    new_name = payload.get("new_name")
    if not all(isinstance(v, str) and v for v in (project_id, node_id, old_name, new_name)):
        raise ValueError("v2.rename_rewrite payload missing project_id/node_id/old_name/new_name")
    assert isinstance(project_id, str)
    assert isinstance(node_id, str)
    assert isinstance(old_name, str)
    assert isinstance(new_name, str)

    db = SessionLocal()
    try:
        renamed = db.get(Node, node_id)
        if renamed is None or renamed.project_id != project_id:
            logger.warning(
                "v2.rename_rewrite: node %s not found in project %s — skipping",
                node_id,
                project_id,
            )
            return

        # 1. Renamed node + its own fragments.
        await _rewrite_node_and_fragments(db, project_id, renamed, old_name, new_name)

        # 2. Direct consumers (reference / dependency edges at the renamed node).
        for consumer in _collect_consumers(db, project_id, node_id):
            try:
                await _rewrite_node_and_fragments(db, project_id, consumer, old_name, new_name)
            except Exception:
                # Per the Phase 11 plan: consumer rewrite failures are
                # logged + skipped; the rename itself must still commit.
                logger.exception(
                    "v2.rename_rewrite: consumer rewrite failed for node %s",
                    consumer.id,
                )

        # 3. The canonical name event flushes last so replay lands
        #    name + prose rewrites in dependency order.
        append_event(
            db,
            project_id,
            ev.NodeRenamed(node_id=node_id, new_name=new_name),
        )

        commit_and_publish(db, project_id)
    finally:
        db.close()


def register() -> None:
    """Register the rename_rewrite handler with the pipeline queue."""
    pipeline_queue.register_handler(RENAME_REWRITE_JOB_TYPE, _handle)
