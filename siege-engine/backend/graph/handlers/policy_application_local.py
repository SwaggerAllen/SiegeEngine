"""Component-local policy application handler.

Registered as ``v2.apply_component_local_policies``. Triggered
by comparch_mint after a top-level component's arch doc is
approved and its component-local policies are minted.

Scope: for each subcomponent under the owning component, decide
which of the owning component's *component-local* policies
apply. Emits ``policy_application`` edges from the applicable
policies to the target subcomponent.

Strategy: one LLM call per subcomponent against the same
candidate set. Keeps prompts bounded and makes failure isolation
easy. If the component has no subcomponents (un-fanned-out) or
no component-local policies, the handler is a no-op.

Shares the stage 5 prompt + validator (``prompts/policy_application.py``
+ ``validators.validate_policy_applications``). The only
differences from the top-level pass are the target scope (each
subcomponent in turn rather than the top-level comp) and the
candidate source (parent comp's local policies rather than the
project-wide top-level set).

See ``docs/architecture/v2-roadmap.md`` Phase 4.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, best_layered_fragment_content
from backend.graph.handlers._bootstrap_generation import run_parse_validate_loop
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    validate_policy_applications,
    validate_policy_blob,
)
from backend.graph.parsers.xml_sections import extract_tag_tree
from backend.graph.prompts.policy_application import (
    SYSTEM_PROMPT,
    format_candidate_policies,
    render_user_prompt,
)
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Edge, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

APPLY_COMPONENT_LOCAL_POLICIES_JOB_TYPE = "v2.apply_component_local_policies"


class ComponentLocalPolicyApplicationError(RuntimeError):
    """Raised when the handler cannot proceed."""


class ComponentLocalPolicyApplicationRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted."""


async def apply_component_local_policies(payload: dict) -> None:
    """Job handler for ``v2.apply_component_local_policies``.

    Payload: ``{"project_id": str, "component_id": str}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise ComponentLocalPolicyApplicationError(
            "apply_component_local_policies payload missing project_id"
        )
    if not isinstance(component_id, str) or not component_id:
        raise ComponentLocalPolicyApplicationError(
            "apply_component_local_policies payload missing component_id"
        )

    db = SessionLocal()
    try:
        comp_node = db.get(Node, component_id)
        if comp_node is None or comp_node.project_id != project_id:
            raise ComponentLocalPolicyApplicationError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )

        # Load the component's component-local policies (parent_id
        # is the owning component).
        local_policies = list(
            db.execute(
                select(Node)
                .where(
                    Node.project_id == project_id,
                    Node.tier == "policy",
                    Node.parent_id == component_id,
                )
                .order_by(Node.display_order.asc(), Node.id.asc())
            ).scalars()
        )
        if not local_policies:
            logger.info(
                "apply_component_local_policies project=%s comp=%s no local policies, no-op",
                project_id,
                component_id,
            )
            return

        # Load subcomponents (targets).
        subcomponents = list(
            db.execute(
                select(Node)
                .where(
                    Node.project_id == project_id,
                    Node.tier == "comp",
                    Node.parent_id == component_id,
                )
                .order_by(Node.display_order.asc(), Node.id.asc())
            ).scalars()
        )
        if not subcomponents:
            logger.info(
                "apply_component_local_policies project=%s comp=%s no subcomponents, no-op",
                project_id,
                component_id,
            )
            return

        # Build the candidate policy context once — it's the same
        # set for every subcomponent. Use a project-wide resp id
        # set so the blob parser doesn't reject cross-reference IDs.
        all_resp_ids: set[str] = set(
            db.execute(
                select(Node.id).where(Node.project_id == project_id, Node.tier == "resp")
            ).scalars()
        )
        candidate_dicts: list[dict] = []
        for policy in local_policies:
            try:
                parsed = validate_policy_blob(policy.content, known_resp_ids=all_resp_ids)
                candidate_dicts.append(
                    {
                        "id": policy.id,
                        "name": parsed.name,
                        "trigger": parsed.trigger,
                        "required": parsed.required_resp_id,
                        "rationale": parsed.rationale,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "apply_component_local_policies project=%s comp=%s "
                    "skipping policy %s: unparseable blob (%s)",
                    project_id,
                    component_id,
                    policy.id,
                    exc,
                )
                continue

        if not candidate_dicts:
            return
        candidate_ids: set[str] = {c["id"] for c in candidate_dicts}
        candidates_summary = format_candidate_policies(candidate_dicts)

        # For each subcomponent, build its own target summary and
        # run a scoped LLM call. Filter out subcomponents that
        # already have application edges for this full candidate
        # set (idempotency: only run the subcomps that are missing
        # at least one candidate).
        targets_to_process: list[tuple[Node, str, str, str]] = []
        for sub in subcomponents:
            # Which policies are already applied to this sub?
            applied_to_sub: set[str] = set(
                db.execute(
                    select(Edge.source_id).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "policy_application",
                        Edge.target_id == sub.id,
                    )
                ).scalars()
            )
            if candidate_ids.issubset(applied_to_sub):
                logger.info(
                    "apply_component_local_policies project=%s comp=%s "
                    "sub=%s all candidates already applied, skipping",
                    project_id,
                    component_id,
                    sub.id,
                )
                continue

            # Layered read so the local-policy prompt sees the
            # rich subcomparch content when available, falling back
            # to the comparch-mint skeletal seed.
            techspec = best_layered_fragment_content(db, sub, FragmentKind.TECHSPEC)
            pubapi = best_layered_fragment_content(db, sub, FragmentKind.PUBAPI)
            targets_to_process.append(
                (
                    sub,
                    techspec,
                    pubapi,
                    _format_sub_responsibilities(db, project_id, sub),
                )
            )

        if not targets_to_process:
            logger.info(
                "apply_component_local_policies project=%s comp=%s all "
                "subcomponents fully applied, no-op",
                project_id,
                component_id,
            )
            return

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_config = settings.to_cli_config()

        # Project vocabulary scoped to this component's reachable
        # features. Component-local policy application reasons
        # about one subcomponent at a time (under the component
        # the policies were minted under), so feature-local vocab
        # filters by that parent component's subtree.
        from backend.graph.vocabulary import render_vocab_summary_for_node

        vocab_summary = render_vocab_summary_for_node(db, project_id, component_id)

        # Referenced content — per sub target. Each sub may have
        # its own outgoing ``reference`` edges.
        from backend.graph.references import render_referenced_content_summary

        referenced_content_by_sub: dict[str, str] = {
            sub.id: render_referenced_content_summary(db, project_id, sub.id)
            for sub, _ts, _pa, _rs in targets_to_process
        }
    finally:
        db.close()

    # ── Phase 2: per-subcomponent LLM calls ─────────────────────────
    logger.info(
        "apply_component_local_policies project=%s comp=%s targets=%d candidates=%d",
        project_id,
        component_id,
        len(targets_to_process),
        len(candidate_dicts),
    )

    for sub, sub_techspec, sub_pubapi, sub_resp_summary in targets_to_process:
        target_summary = f"**{sub.name}** (`{sub.id}`) — subcomponent of {component_id}"

        sub_referenced_content = referenced_content_by_sub.get(sub.id, "")

        def _render(
            *,
            prior_pending,
            parse_error,
            _sub_techspec=sub_techspec,
            _sub_pubapi=sub_pubapi,
            _resp_summary=sub_resp_summary,
            _target_summary=target_summary,
            _sub_refs=sub_referenced_content,
        ):
            return render_user_prompt(
                target_summary=_target_summary,
                target_techspec=_sub_techspec,
                target_pubapi=_sub_pubapi,
                target_responsibilities_summary=_resp_summary,
                candidate_policies_summary=candidates_summary,
                scope="component-local",
                parse_error=parse_error,
                vocab_summary=vocab_summary,
                referenced_content_summary=_sub_refs,
            )

        def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
            validate_policy_applications(tree, known_policy_ids=candidate_ids)

        validated_output, _attempts = await run_parse_validate_loop(
            root_tag="policy-applications",
            system_prompt=SYSTEM_PROMPT,
            cli_config=cli_config,
            prior_pending=None,
            render_prompt=_render,
            validate=_validate,
            exhausted_exception_cls=ComponentLocalPolicyApplicationRetryExhausted,
            log_handler_name=f"apply_component_local_policies:{sub.id}",
        )

        tree = extract_tag_tree(validated_output.text, "policy-applications")
        decisions = validate_policy_applications(tree, known_policy_ids=candidate_ids)

        # Emit edges for the applies decisions
        db = SessionLocal()
        try:
            for decision in decisions:
                if not decision.applies:
                    logger.info(
                        "apply_component_local_policies project=%s comp=%s "
                        "sub=%s policy=%s does-not-apply: %s",
                        project_id,
                        component_id,
                        sub.id,
                        decision.policy_id,
                        decision.rationale[:200],
                    )
                    continue
                edge_id = mint(db, Kind.EDGE)
                append_event(
                    db,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="policy_application",
                        source_id=decision.policy_id,
                        target_id=sub.id,
                    ),
                )
                logger.info(
                    "apply_component_local_policies project=%s comp=%s "
                    "sub=%s policy=%s applies: %s",
                    project_id,
                    component_id,
                    sub.id,
                    decision.policy_id,
                    decision.rationale[:200],
                )
            db.commit()
        finally:
            db.close()


def _format_sub_responsibilities(session, project_id: str, sub_node: Node) -> str:
    """Render a subcomponent's responsibilities as a prompt bullet list.

    Subcomponents own subresps via decomposition edges (subresp →
    sub_comp). Walk those edges and render the source subresps.
    """
    rows = session.execute(
        select(Node)
        .join(Edge, Edge.source_id == Node.id)
        .where(
            Edge.edge_type == "decomposition",
            Edge.target_id == sub_node.id,
            Node.tier == "resp",
            Node.project_id == project_id,
        )
        .order_by(Node.display_order.asc(), Node.id.asc())
    ).scalars()
    lines = []
    for r in rows:
        lines.append(f"- `{r.id}` **{r.name}**: {(r.content or '').strip()}")
    return "\n".join(lines) if lines else ""


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(
        APPLY_COMPONENT_LOCAL_POLICIES_JOB_TYPE, apply_component_local_policies
    )
