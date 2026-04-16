"""Subrequirements generation handler.

Registered on the pipeline job queue as
``v2.generate_subrequirements``. The payload is
``{"project_id": str, "component_id": str, "feedback": str | None}``.

Per-component variant of the requirements_generation handler.
Gathers inputs scoped to the given component:

- The component's sysarch-time metadata (name, role from
  ``comp_X_techspec`` fragment, api-intent from
  ``comp_X_pubapi`` fragment).
- The top-level ``resp_*`` nodes assigned to this component via
  the ``decomposition`` edges minted at sysarch approval.
- Prior pending draft for this component's subreqs node (if any).

Validator takes ``known_parent_resp_ids`` — the set of top-level
resp IDs assigned to this component — and enforces that every
``<derived-from>`` reference stays within that set. Cross-
component leaks become parse errors that feed the retry loop.

See ``docs/architecture/v2-roadmap.md`` Phase 3 stage 3 and
``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers._bootstrap_generation import (
    persist_draft,
    run_parse_validate_loop,
)
from backend.graph.parsers.validators import validate_subrequirements
from backend.graph.prompts.subrequirements import (
    format_component_summary,
    format_domain_parent_context,
    format_parent_resps_summary,
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.queries import (
    domain_parents_of,
    list_subresponsibilities,
    top_level_resps_assigned_to,
)
from backend.graph.subrequirements import (
    get_subreqs_node,
    pending_subreqs_draft,
)
from backend.models import Project
from backend.models.node import Fragment, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_SUBREQS_JOB_TYPE = "v2.generate_subrequirements"


class SubreqsHandlerError(RuntimeError):
    """Raised when the handler cannot proceed."""


class SubreqsParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted."""


async def generate_subreqs(payload: dict) -> None:
    """Job handler for ``v2.generate_subrequirements``.

    Payload shape: ``{"project_id": str, "component_id": str,
    "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise SubreqsHandlerError("generate_subreqs payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise SubreqsHandlerError("generate_subreqs payload missing component_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        comp_node = db.get(Node, component_id)
        if comp_node is None or comp_node.project_id != project_id:
            raise SubreqsHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )
        if comp_node.tier != "comp":
            raise SubreqsHandlerError(
                f"Node {component_id!r} is not a comp_* node (tier={comp_node.tier!r})"
            )

        subreqs_node = get_subreqs_node(db, project_id, component_id)
        if subreqs_node is None:
            raise SubreqsHandlerError(
                f"Component {component_id!r} has no subreqs node; "
                "was bootstrap_subreqs_node called at mint_sysarch time?"
            )
        subreqs_node_id: str = subreqs_node.id
        prior_approved: str | None = subreqs_node.content or None

        pending = pending_subreqs_draft(db, project_id, component_id)
        prior_pending: str | None = pending.content if pending else None
        prior_pending_id: str | None = pending.id if pending else None

        # Component metadata for the prompt: name + role + api-intent.
        # Role and api-intent live in fragments written by the
        # sysarch mint handler.
        role = _read_fragment(db, component_id, FragmentKind.TECHSPEC) or ""
        api_intent = _read_fragment(db, component_id, FragmentKind.PUBAPI) or ""
        component_summary = format_component_summary(
            name=comp_node.name, role=role, api_intent=api_intent
        )

        # Parent resps — the top-level resps assigned to this
        # component via decomposition edges. This is the set the
        # validator's coverage check enforces.
        parent_resp_rows = top_level_resps_assigned_to(db, component_id)
        parent_resps_summary = format_parent_resps_summary(
            [{"id": r.id, "name": r.name, "content": r.content} for r in parent_resp_rows]
        )
        known_parent_resp_ids: set[str] = {r.id for r in parent_resp_rows}

        # Domain-parent context — only populated when this is a
        # presentational component with domain_parent edges that
        # point at domain components whose own subreqs have
        # already been minted. Rendered into the prompt as a
        # read-only block so the LLM can align UI-side subresps
        # with the domain side without duplicating. Cross-
        # component references remain forbidden by the validator;
        # this is advisory context only.
        #
        # If the presentational component's subreqs generation
        # runs before any of its domain parents have approved
        # subreqs (possible under the sysarch-mint fan-out
        # ordering, which doesn't sequence domain before
        # presentational), the context block is empty and the
        # LLM falls back to writing subresps from scratch. A
        # later regen once the domain side is minted will pick
        # up the context.
        domain_parent_context: str | None = None
        if comp_node.kind == "presentational":
            parent_rows = domain_parents_of(db, component_id)
            parent_bundles: list[dict] = []
            for parent in parent_rows:
                parent_subresps = list_subresponsibilities(db, parent.id)
                parent_bundles.append(
                    {
                        "name": parent.name,
                        "subresps": [
                            {
                                "id": sr.id,
                                "name": sr.name,
                                "content": sr.content,
                            }
                            for sr in parent_subresps
                        ],
                    }
                )
            rendered = format_domain_parent_context(parent_bundles)
            domain_parent_context = rendered or None

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        system_prompt = render_system_prompt()

        # Project vocabulary scoped to this component's reachable
        # features via the decomposition walk. The subreqs regen
        # is scoped to one top-level component, so it only needs
        # vocab for the features that component's responsibilities
        # serve, plus project-level vocab.
        from backend.graph.vocabulary import render_vocab_summary_for_node

        vocab_summary = render_vocab_summary_for_node(db, project_id, component_id)
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_subreqs project=%s comp=%s prior_pending=%s feedback=%s parents=%d",
        project_id,
        component_id,
        bool(prior_pending),
        bool(feedback),
        len(parent_resp_rows),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            component_summary=component_summary,
            parent_resps_summary=parent_resps_summary,
            domain_parent_context=domain_parent_context,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
            vocab_summary=vocab_summary,
        )

    def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_subrequirements(tree, known_parent_resp_ids=known_parent_resp_ids)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="subrequirements",
        system_prompt=system_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=SubreqsParseRetryExhausted,
        log_handler_name="generate_subreqs",
    )

    persist_draft(
        project_id=project_id,
        node_id=subreqs_node_id,
        section="subrequirements",
        validated_output=validated_output,
        attempts=attempts,
        prior_pending_id=prior_pending_id,
        log_handler_name="generate_subreqs",
    )


def _read_fragment(db, owner_id: str, kind: FragmentKind) -> str | None:
    """Read a fragment's content by (owner, kind), or return None."""
    fid = fragment_id(owner_id, kind)
    frag = db.get(Fragment, fid)
    return frag.content if frag is not None else None


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_SUBREQS_JOB_TYPE, generate_subreqs)
