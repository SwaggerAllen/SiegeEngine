"""Implementation (impl) generation handler.

Registered on the pipeline job queue as ``v2.generate_impl``.
Payload: ``{"project_id": str, "owner_id": str, "feedback": str | None}``.

Phase 8 counterpart to the comparch / subcomparch generation
handlers. The ``owner_id`` is the comp_* that OWNS the impl —
either a subcomponent (for per-sub impls) or an un-fanned-out
top-level comp (for un-fanned-out impls). The impl node itself
lives as a child of the owner with ``tier="impl"`` and
``parent_id=owner_id``.

Three-phase shape:

1. **Gather inputs.** Resolve the owner comp, verify its
   comparch/subcomparch is approved (its ``Node.content`` is
   non-empty), locate the impl shell minted by comparch_mint,
   assemble the :class:`RegenContext` bundle and format it
   via :func:`format_regen_context_for_impl`.
2. **LLM call + parse-validate retry loop.** Delegate to
   ``run_parse_validate_loop`` with the impl prompt and the
   ``<implementation>`` validator. The prose sections are
   opaque so there are no known-ID sets to feed in.
3. **Persist events + telemetry.** DraftDiscarded for any prior
   pending, DraftGenerated targeting the impl node itself, one
   ``GenerationTelemetry`` row per attempt with
   ``section="impl"``.

Unlike bootstrap tiers, impl content is never frozen after
approval — feedback / regen flow freely post-approval, and the
route layer (``has_been_approved=None`` on ``IMPL_CONFIG``)
enforces that. See ``docs/architecture/v2-rearchitecture.md``
§Implementation nodes and ``docs/architecture/v2-roadmap.md``
Phase 8.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_generation import (
    persist_draft,
    run_parse_validate_loop,
)
from backend.graph.parsers.validators import validate_implementation
from backend.graph.prompts.impl import SYSTEM_PROMPT, render_user_prompt
from backend.graph.regen_context import (
    build_regen_context,
    format_regen_context_for_impl,
)
from backend.models import Project
from backend.models.node import Draft, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_IMPL_JOB_TYPE = "v2.generate_impl"

IMPL_TIER = "impl"


class ImplHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class ImplPreconditionError(ImplHandlerError):
    """Raised when the owner comp's arch doc hasn't been approved yet."""


class ImplParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


def _find_impl_for_owner(db, project_id: str, owner_id: str) -> Node | None:  # type: ignore[no-untyped-def]
    """Return the ``impl_*`` child of ``owner_id``, or None.

    The invariant is one impl per leaf — comparch_mint mints
    exactly one shell per subcomponent and per un-fanned-out
    top-level comp. If none exists, the caller should fail
    fast rather than mint one on the fly.
    """
    return db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == IMPL_TIER,
            Node.parent_id == owner_id,
        )
    ).scalar_one_or_none()


async def generate_impl(payload: dict) -> None:
    """Job handler for ``v2.generate_impl``.

    Payload shape: ``{"project_id": str, "owner_id": str,
    "feedback": str | None}``. ``owner_id`` is the comp_* that
    owns the impl — a subcomponent or an un-fanned-out top-level
    comp.
    """
    project_id = payload.get("project_id")
    owner_id = payload.get("owner_id")
    if not isinstance(project_id, str) or not project_id:
        raise ImplHandlerError("generate_impl payload missing project_id")
    if not isinstance(owner_id, str) or not owner_id:
        raise ImplHandlerError("generate_impl payload missing owner_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        owner_node = db.get(Node, owner_id)
        if owner_node is None or owner_node.project_id != project_id:
            raise ImplHandlerError(
                f"Owner component {owner_id!r} not found in project {project_id!r}"
            )
        if owner_node.tier != "comp":
            raise ImplHandlerError(
                f"Owner {owner_id!r} is not a comp_* node (tier={owner_node.tier!r})"
            )

        # Precondition: the owner's arch doc (comparch for
        # top-level, subcomparch for sub) has been approved. The
        # comparch_mint handler writes Node.content at approval
        # time for top-level comps; subcomparch_mint does the same
        # for subs. Empty content means the arch doc hasn't been
        # approved yet.
        if not (owner_node.content or "").strip():
            raise ImplPreconditionError(
                f"Impl generation for owner {owner_id!r} blocked — its "
                "architecture doc (comparch / subcomparch) has not "
                "yet been approved. Approve the arch doc first."
            )

        impl_node = _find_impl_for_owner(db, project_id, owner_id)
        if impl_node is None:
            raise ImplHandlerError(
                f"Owner {owner_id!r} has no impl shell. "
                "comparch_mint is responsible for minting one impl "
                "shell per subcomponent and per un-fanned-out "
                "top-level comp; this should not happen."
            )
        impl_node_id = impl_node.id

        prior_approved: str | None = impl_node.content or None
        pending = db.execute(
            select(Draft).where(
                Draft.project_id == project_id,
                Draft.target_type == "node",
                Draft.target_id == impl_node_id,
                Draft.status == "pending",
            )
        ).scalar_one_or_none()
        prior_pending: str | None = pending.content if pending is not None else None
        prior_pending_id: str | None = pending.id if pending is not None else None

        # Assemble the regen context keyed on the OWNER (not the
        # impl node). build_regen_context auto-detects top-level
        # vs subcomponent from the owner's parent_id and
        # populates the right fields.
        regen_ctx = build_regen_context(db, owner_id)
        context_kwargs = format_regen_context_for_impl(regen_ctx)

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        cli_max_budget_usd = settings.cli_max_budget_usd
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_impl project=%s owner=%s impl=%s prior_pending=%s feedback=%s",
        project_id,
        owner_id,
        impl_node_id,
        bool(prior_pending),
        bool(feedback),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            **context_kwargs,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
        )

    def _validate(tree, raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_implementation(tree, raw_content=raw_text)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="implementation",
        system_prompt=SYSTEM_PROMPT,
        cli_timeout_seconds=cli_timeout_seconds,
        cli_max_budget_usd=cli_max_budget_usd,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=ImplParseRetryExhausted,
        log_handler_name="generate_impl",
    )

    persist_draft(
        project_id=project_id,
        node_id=impl_node_id,
        section="impl",
        validated_output=validated_output,
        attempts=attempts,
        prior_pending_id=prior_pending_id,
        log_handler_name="generate_impl",
        review_job_type="v2.review_impl",
    )


GENERATE_FANIN_JOB_TYPE = "v2.generate_fanin"


def on_impl_approved(
    db,  # type: ignore[no-untyped-def]
    project_id: str,
    impl_node: Node,
    scope_ids: tuple[str, ...],
) -> None:
    """Post-approval hook: enqueue fan-in regen if this impl is under a fanned-out domain comp.

    Wired into ``IMPL_CONFIG.on_approve``. Called by
    ``bootstrap_approve`` after the reducer commits the
    ``DraftApproved`` event for an impl draft. The hook:

    1. Walks up the impl's parent chain to find the top-level
       comp that owns the subtree this impl lives in.
    2. Checks whether that top-level comp has a ``fanin_*``
       child (minted by ``comparch_mint`` only for fanned-out
       domain comps).
    3. If yes, enqueues ``v2.generate_fanin`` keyed on that
       comp's id. The pipeline_queue's payload-dedup collapses
       rapid-fire impl approvals into a single regen run.

    Presentational subtrees (whose top-level comp is
    presentational and thus has no fan-in) no-op. Un-fanned-out
    domain comps no-op for the same reason — they have no
    fan-in child.

    Failures here must NOT roll back the approval; callers
    (``bootstrap_approve``) wrap this in try/except and swallow
    exceptions after logging.
    """
    _ = scope_ids  # unused — we resolve via the impl node's parent chain
    if impl_node.tier != "impl":
        return

    # Walk up to the top-level comp. Depth is hard-capped at 2
    # comp tiers (comp → subcomp → leaf), so the chain is at most
    # impl → comp → comp.
    current_parent_id = impl_node.parent_id
    top_level: Node | None = None
    while current_parent_id is not None:
        parent = db.get(Node, current_parent_id)
        if parent is None:
            break
        if parent.tier == "comp" and parent.parent_id is None:
            top_level = parent
            break
        current_parent_id = parent.parent_id

    if top_level is None:
        return

    # Only domain comps get fan-ins (presentational comps don't).
    # Check for an actual fan-in child rather than gating on
    # kind alone, so un-fanned-out domain comps also no-op.
    fanin_child = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "fanin",
            Node.parent_id == top_level.id,
        )
    ).scalar_one_or_none()
    if fanin_child is None:
        return

    # Phase 7.5 first-pass gate: hold off on the initial fan-in
    # until every impl under this top-level comp has been approved
    # at least once. Before first-pass, an approval here with only
    # a partial impl set leaves the check False and the enqueue is
    # skipped — the fan-in never fires on an incomplete set.
    #
    # After first-pass, the check returns True on every subsequent
    # approval (all impls remain populated except when reset-cleared)
    # and the enqueue runs. The queue's payload-dedupe collapses
    # bursts of approvals into a single regen.
    from backend.graph.queries import all_impls_populated_for

    if not all_impls_populated_for(db, top_level.id):
        return

    pipeline_queue.enqueue(
        db,
        job_type=GENERATE_FANIN_JOB_TYPE,
        payload={
            "project_id": project_id,
            "owner_comp_id": top_level.id,
        },
    )


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_IMPL_JOB_TYPE, generate_impl)
