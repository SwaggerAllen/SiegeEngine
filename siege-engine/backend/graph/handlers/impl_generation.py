"""Implementation (impl) generation handler.

Registered on the pipeline job queue as ``v2.generate_impl``.
Payload: ``{"project_id": str, "owner_id": str, "feedback": str | None}``.

The ``owner_id`` is the comp_* that OWNS the impl — either a
subcomponent (per-sub impl) or an un-fanned-out top-level comp.
The impl node itself is a child of the owner with ``tier="impl"``.

Phase C migration: handler delegates to
:func:`backend.graph.handlers._tier_generation.run_tier_generation`.
The structural checks (owner exists, tier=comp) move to
:func:`owner_node_exists`; the parent-arch-approved check moves to
:func:`owner_arch_approved`. Both compose via :func:`all_of` on
``IMPL_CONFIG.readiness_check``.

The ``on_impl_approved`` post-approval hook stays in this module
and is wired via ``IMPL_CONFIG.on_approve`` in
``bootstrap_routes.py``. Phase E migrates it into
``IMPL_CONFIG.post_persist_hooks``.

See ``docs/architecture/v2-rearchitecture.md`` §Implementation
nodes and ``docs/architecture/v2-roadmap.md`` Phase 8.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.handlers._readiness import (
    all_of,
    owner_arch_approved,
    owner_node_exists,
)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierPreconditionError,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import validate_implementation
from backend.graph.parsers.xml_sections import TagNode
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
GENERATE_FANIN_JOB_TYPE = "v2.generate_fanin"
IMPL_TIER = "impl"


class ImplHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class ImplPreconditionError(ImplHandlerError):
    """Raised when the owner comp's arch doc hasn't been approved yet."""


class ImplParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


@dataclass
class ImplState:
    """Per-tier state bundle for impl generation."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    context_kwargs: dict


def _find_impl_for_owner(db: Session, project_id: str, owner_id: str) -> Node | None:
    """Return the ``impl_*`` child of ``owner_id``, or None.

    The invariant is one impl per leaf — comparch_mint mints
    exactly one shell per subcomponent and per un-fanned-out
    top-level comp.
    """
    return db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == IMPL_TIER,
            Node.parent_id == owner_id,
        )
    ).scalar_one_or_none()


def gather_impl_state(db: Session, project_id: str, scope_ids: tuple[str, ...]) -> ImplState:
    if not scope_ids:
        raise ImplHandlerError("generate_impl payload missing owner_id")
    owner_id = scope_ids[0]

    # Defensive — readiness predicate already gates these.
    owner_node = db.get(Node, owner_id)
    if owner_node is None or owner_node.project_id != project_id:
        raise ImplHandlerError(f"Owner component {owner_id!r} not found in project {project_id!r}")

    impl_node = _find_impl_for_owner(db, project_id, owner_id)
    if impl_node is None:
        raise ImplHandlerError(
            f"Owner {owner_id!r} has no impl shell. "
            "comparch_mint is responsible for minting one impl "
            "shell per subcomponent and per un-fanned-out "
            "top-level comp; this should not happen."
        )

    pending = db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == impl_node.id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()

    # Regen context is keyed on the OWNER, not the impl node.
    regen_ctx = build_regen_context(db, owner_id)
    context_kwargs = format_regen_context_for_impl(regen_ctx)

    project_row = db.get(Project, project_id)
    assert project_row is not None
    settings = get_project_settings(project_row)

    return ImplState(
        node_id=impl_node.id,
        prior_approved=impl_node.content or None,
        prior_pending=pending.content if pending is not None else None,
        prior_pending_id=pending.id if pending is not None else None,
        cli_config=settings.to_cli_config(),
        system_prompt=SYSTEM_PROMPT,
        context_kwargs=context_kwargs,
    )


def _render_impl_prompt(
    state: ImplState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        **state.context_kwargs,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
    )


def _validate_impl(tree: TagNode, raw_text: str, _state: ImplState) -> None:
    validate_implementation(tree, raw_content=raw_text)


IMPL_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="impl",
    generate_job_type=GENERATE_IMPL_JOB_TYPE,
    section="impl",
    root_tag="implementation",
    exhausted_exception_cls=ImplParseRetryExhausted,
    gather_state=gather_impl_state,  # type: ignore[arg-type]
    render_prompt=_render_impl_prompt,  # type: ignore[arg-type]
    validate=_validate_impl,  # type: ignore[arg-type]
    review_job_type="v2.review_impl",
    scope_payload_keys=("owner_id",),
    max_auto_revisions=5,
    readiness_check=all_of(owner_node_exists, owner_arch_approved),
)


async def generate_impl(payload: dict) -> None:
    """Job handler for ``v2.generate_impl``.

    Phase C migration: delegates to :func:`run_tier_generation`. The
    thin wrapper converts driver-level errors:

    - ``ValueError`` (payload-shape) → :class:`ImplHandlerError`.
    - ``TierPreconditionError`` from ``owner_arch_approved`` (message
      contains "has not yet been approved" or "blocked") →
      :class:`ImplPreconditionError`.
    - All other ``TierPreconditionError`` (owner missing / wrong tier)
      → :class:`ImplHandlerError`.
    """
    try:
        await run_tier_generation(payload, IMPL_CONFIG)
    except TierPreconditionError as exc:
        msg = str(exc)
        if "has not yet been approved" in msg or "blocked" in msg:
            raise ImplPreconditionError(msg) from exc
        raise ImplHandlerError(msg) from exc
    except ValueError as exc:
        raise ImplHandlerError(str(exc)) from exc


def on_impl_approved(
    db: Session,
    project_id: str,
    impl_node: Node,
    scope_ids: tuple[str, ...],
) -> None:
    """Post-approval hook: enqueue fan-in regen if this impl is under a fanned-out domain comp.

    Wired into ``IMPL_CONFIG.on_approve`` in ``bootstrap_routes.py``.
    Phase E migrates this into the driver's
    ``post_persist_hooks`` so the wiring is uniform across tiers.

    1. Walks up the impl's parent chain to find the top-level
       comp that owns the subtree this impl lives in.
    2. Checks whether that top-level comp has a ``fanin_*`` child
       (minted by ``comparch_mint`` only for fanned-out domain comps).
    3. If yes AND every impl under that subtree has approved content
       (first-pass gate), enqueues ``v2.generate_fanin``.
    """
    _ = scope_ids  # unused — we resolve via the impl node's parent chain
    if impl_node.tier != "impl":
        return

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

    fanin_child = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "fanin",
            Node.parent_id == top_level.id,
        )
    ).scalar_one_or_none()
    if fanin_child is None:
        return

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


_: type = TierState
