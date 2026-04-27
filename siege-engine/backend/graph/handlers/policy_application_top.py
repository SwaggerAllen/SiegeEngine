"""Top-level policy application handler.

Registered on the pipeline job queue as
``v2.apply_top_level_policies``. Triggered by the comparch mint
handler after a component's arch doc is approved and minted.

For a given component, loads every top-level ``policy_*``
candidate (project-wide policies, ``parent_id IS NULL``) that
doesn't already have a ``policy_application`` edge targeting
this component, makes one LLM call that decides applies/
doesn't-apply for each candidate, and emits
``policy_application`` edges for the applies side.

Additionally: if an applied policy's ``<required>`` resp is
owned by a different component and this component lacks a
dependency edge to the owning component, the handler patches
in a missing ``dependency`` edge. This is the "policy-induced
dep edge" patching from the Phase 4 roadmap — makes sure the
required responsibility is actually reachable from the site
where the policy fires.

Idempotency: policies with an existing ``policy_application``
edge to this component are excluded from the candidate set at
load time, so a re-run is a no-op. If all candidates are
already applied, the handler skips the LLM call entirely and
returns without work.

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
from backend.graph.prompts.policy_application import (
    SYSTEM_PROMPT,
    format_candidate_policies,
    render_user_prompt,
)
from backend.graph.queries import top_level_resps_assigned_to
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Edge, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

APPLY_TOP_LEVEL_POLICIES_JOB_TYPE = "v2.apply_top_level_policies"


class PolicyApplicationHandlerError(RuntimeError):
    """Raised when the handler cannot proceed."""


class PolicyApplicationParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted."""


async def apply_top_level_policies(payload: dict) -> None:
    """Job handler for ``v2.apply_top_level_policies``.

    Payload: ``{"project_id": str, "component_id": str}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise PolicyApplicationHandlerError("apply_top_level_policies payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise PolicyApplicationHandlerError("apply_top_level_policies payload missing component_id")

    db = SessionLocal()
    try:
        comp_node = db.get(Node, component_id)
        if comp_node is None or comp_node.project_id != project_id:
            raise PolicyApplicationHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )

        # Load top-level policies without an existing application edge
        # to this component (idempotency).
        already_applied_ids: set[str] = set(
            db.execute(
                select(Edge.source_id).where(
                    Edge.project_id == project_id,
                    Edge.edge_type == "policy_application",
                    Edge.target_id == component_id,
                )
            ).scalars()
        )
        candidates = [
            p
            for p in db.execute(
                select(Node)
                .where(
                    Node.project_id == project_id,
                    Node.tier == "policy",
                    Node.parent_id.is_(None),
                )
                .order_by(Node.display_order.asc(), Node.id.asc())
            ).scalars()
            if p.id not in already_applied_ids
        ]

        if not candidates:
            logger.info(
                "apply_top_level_policies project=%s comp=%s no candidates, no-op",
                project_id,
                component_id,
            )
            return

        # Target context: component name, techspec, pubapi, resps.
        # Layered read so the policy-application prompt sees the
        # rich comparch content when available, falling back to the
        # sysarch skeletal seed otherwise.
        techspec = best_layered_fragment_content(db, comp_node, FragmentKind.TECHSPEC)
        pubapi = best_layered_fragment_content(db, comp_node, FragmentKind.PUBAPI)

        parent_resps = top_level_resps_assigned_to(db, component_id)

        # Per-candidate context: parse the inline <policy> blob to
        # extract trigger + required + rationale. Top-level policies
        # reference resps that may live in OTHER components' scopes,
        # so the per-policy known_resp_ids check inside
        # validate_policy_blob is over-tight — use a project-wide
        # resp id set for the blob parsing.
        all_resp_ids: set[str] = set(
            db.execute(
                select(Node.id).where(Node.project_id == project_id, Node.tier == "resp")
            ).scalars()
        )

        candidate_dicts: list[dict] = []
        for policy in candidates:
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
                # Policy blob unparseable — skip with a warning.
                # The mint handler produced this blob so it should
                # always parse, but be defensive.
                logger.warning(
                    "apply_top_level_policies project=%s comp=%s skipping "
                    "policy %s: unparseable blob (%s)",
                    project_id,
                    component_id,
                    policy.id,
                    exc,
                )
                continue

        if not candidate_dicts:
            return

        candidate_ids: set[str] = {c["id"] for c in candidate_dicts}

        # Render prompt context
        target_summary = f"**{comp_node.name}** (`{comp_node.id}`)"
        resp_lines: list[str] = []
        for r in parent_resps:
            resp_lines.append(f"- `{r.id}` **{r.name}**: {(r.content or '').strip()}")
        resp_summary = "\n".join(resp_lines)
        candidates_summary = format_candidate_policies(candidate_dicts)

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_config = settings.to_cli_config()

        # Project vocabulary scoped to this component's reachable
        # features, same as the subreqs / comparch / subcomparch
        # tiers. Policy application reasons about one component
        # at a time, so feature-local vocab is filtered by that
        # component's reachable subtree.
        from backend.graph.vocabulary import render_vocab_summary_for_node

        vocab_summary = render_vocab_summary_for_node(db, project_id, component_id)

        from backend.graph.references import render_referenced_content_summary

        referenced_content_summary = render_referenced_content_summary(db, project_id, component_id)
    finally:
        db.close()

    # ── Phase 2: LLM call ───────────────────────────────────────────
    logger.info(
        "apply_top_level_policies project=%s comp=%s candidates=%d",
        project_id,
        component_id,
        len(candidate_dicts),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            target_summary=target_summary,
            target_techspec=techspec,
            target_pubapi=pubapi,
            target_responsibilities_summary=resp_summary,
            candidate_policies_summary=candidates_summary,
            scope="top-level",
            parse_error=parse_error,
            vocab_summary=vocab_summary,
            referenced_content_summary=referenced_content_summary,
        )

    def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_policy_applications(tree, known_policy_ids=candidate_ids)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="policy-applications",
        system_prompt=SYSTEM_PROMPT,
        cli_config=cli_config,
        prior_pending=None,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=PolicyApplicationParseRetryExhausted,
        log_handler_name="apply_top_level_policies",
    )

    # ── Phase 3: parse decisions + emit edges + patch deps ──────────
    from backend.graph.parsers.xml_sections import extract_tag_tree

    tree = extract_tag_tree(validated_output.text, "policy-applications")
    decisions = validate_policy_applications(tree, known_policy_ids=candidate_ids)

    db = SessionLocal()
    try:
        applied_count = 0
        patched_dep_count = 0
        for decision in decisions:
            if not decision.applies:
                logger.info(
                    "apply_top_level_policies project=%s comp=%s policy=%s does-not-apply: %s",
                    project_id,
                    component_id,
                    decision.policy_id,
                    decision.rationale[:200],
                )
                continue

            # Emit policy_application edge policy -> component
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="policy_application",
                    source_id=decision.policy_id,
                    target_id=component_id,
                ),
            )
            applied_count += 1

            logger.info(
                "apply_top_level_policies project=%s comp=%s policy=%s applies: %s",
                project_id,
                component_id,
                decision.policy_id,
                decision.rationale[:200],
            )

            # Patch missing dependency edge if the policy's required
            # resp is owned by a DIFFERENT component and the current
            # component doesn't already depend on that owner.
            required_comp_id = _find_required_resp_owner(db, project_id, decision.policy_id)
            if required_comp_id and required_comp_id != component_id:
                has_dep = db.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "dependency",
                        Edge.source_id == component_id,
                        Edge.target_id == required_comp_id,
                    )
                ).first()
                if has_dep is None:
                    dep_edge_id = mint(db, Kind.EDGE)
                    append_event(
                        db,
                        project_id,
                        ev.EdgeCreated(
                            edge_id=dep_edge_id,
                            edge_type="dependency",
                            source_id=component_id,
                            target_id=required_comp_id,
                        ),
                    )
                    patched_dep_count += 1
                    logger.info(
                        "apply_top_level_policies project=%s comp=%s "
                        "patched missing dep edge -> %s (policy-induced)",
                        project_id,
                        component_id,
                        required_comp_id,
                    )

        db.commit()
        logger.info(
            "apply_top_level_policies project=%s comp=%s committed "
            "(applied=%d, patched_deps=%d, total_candidates=%d)",
            project_id,
            component_id,
            applied_count,
            patched_dep_count,
            len(decisions),
        )
    finally:
        db.close()


def _find_required_resp_owner(session, project_id: str, policy_id: str) -> str | None:
    """Return the comp_id that owns the resp a policy's <required>
    points at, or None if the resp has no owning component.

    Walks: policy_* content -> parse blob -> required resp_* ->
    decomposition edge (resp → comp) or parent_id (sub resp).
    Returns the comp_* that the resp decomposes into or is
    parented to; None if neither path resolves.
    """
    from backend.graph.parsers.xml_sections import extract_tag_tree

    policy_node = session.get(Node, policy_id)
    if policy_node is None:
        return None
    try:
        tree = extract_tag_tree(policy_node.content, "policy")
    except Exception:
        return None

    required_el = tree.find_all("required")
    if not required_el:
        return None
    required_resp_id = (required_el[0].text or "").strip()
    if not required_resp_id:
        return None

    resp_node = session.get(Node, required_resp_id)
    if resp_node is None:
        return None

    # If the resp is a subresp (parent_id is a comp), that's the owner.
    if resp_node.parent_id:
        parent = session.get(Node, resp_node.parent_id)
        if parent is not None and parent.tier == "comp":
            return parent.id

    # Otherwise the owner is whichever comp the resp decomposes into
    # via a decomposition edge.
    edge_row = session.execute(
        select(Edge).where(
            Edge.project_id == project_id,
            Edge.edge_type == "decomposition",
            Edge.source_id == required_resp_id,
        )
    ).scalar_one_or_none()
    if edge_row is None:
        return None
    target_node = session.get(Node, edge_row.target_id)
    if target_node is None or target_node.tier != "comp":
        return None
    return target_node.id


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(APPLY_TOP_LEVEL_POLICIES_JOB_TYPE, apply_top_level_policies)
