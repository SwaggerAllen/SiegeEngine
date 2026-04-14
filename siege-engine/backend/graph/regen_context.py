"""Shared regen-context helper for per-component generation passes.

Phase 4 comparch, Phase 5 subcomponent arch docs, and every later
per-component regen pass (policy application, impl, plan, code)
need roughly the same bundle of context to do a good job: the
component's own metadata, its parent responsibilities and
pre-minted subresponsibilities, the public surfaces of its
dependencies, the top-level policy candidates it might fulfill,
the policies that have already been applied to it, and any
relevant feature context. Collecting all of that inline in each
handler would produce a lot of near-duplicate code and make
future additions (like neighbor diffs) hard to land in one place.

This module owns the gather + format pattern. Callers do:

    ctx = build_regen_context(session, comp_id)
    context_kwargs = format_regen_context(ctx)
    user_prompt = render_user_prompt(
        **context_kwargs,
        prior_approved=prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        parse_error=parse_error,
    )

``build_regen_context`` reads from the DB; ``format_regen_context``
is pure and converts the dataclass to the markdown-ish strings
that the comparch (and later-phase) prompts consume as their
context kwargs.

See ``docs/architecture/v2-roadmap.md`` Phase 4 ("shared regen
helper lands here, built as a primitive from the start, not
retrofitted later").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.queries import (
    get_component_context,
    list_top_level_components,
)
from backend.models.node import Edge, Fragment, Node


@dataclass(frozen=True)
class RegenContext:
    """Everything a per-component regen pass needs to generate.

    Fields are read-only ORM snapshots plus derived dicts. The
    dataclass is constructed once at the top of each regen and
    handed down; individual handlers never walk the DB for this
    bundle a second time.

    - ``component``: the component Node this regen is for.
    - ``component_techspec`` / ``component_pubapi``: content of
      this component's techspec + pubapi fragments (empty string
      if not minted yet — sysarch_mint writes skeletal
      placeholders, so they're normally populated).
    - ``parent_resps``: top-level resps assigned to this component
      via decomposition edges at sysarch approval.
    - ``subresps``: pre-minted subresps under this component
      (parent_id = comp_id, from subreqs approval).
    - ``related_features``: features reachable via the
      decomposition walk ``feat_* → resp_* → comp_*`` — the
      ultimate source of user-visible work this component serves.
    - ``sibling_comp_ids``: every top-level comp_* in the project
      except this one. The allowed set for ``<dependencies>``
      references in the comparch arch doc.
    - ``sibling_comps``: the Node rows for those siblings, for
      rendering names + roles in context.
    - ``dep_pubapi_fragments``: mapping of sibling comp_id →
      pubapi content for every sibling this component already
      depends on (per existing dependency edges). Missing entries
      get an empty string — normal on first-run comparch when the
      target sibling hasn't been architected yet.
    - ``top_level_policy_candidates``: all top-level ``policy_*``
      nodes (parent_id is None). Informational — the application
      pass that runs after comparch approval decides which apply.
    - ``already_applied_policies``: policies with an existing
      ``policy_application`` edge targeting this component.
      Informational — the application pass excludes these from
      its candidate set for idempotency, and the prompt mentions
      them so the LLM doesn't try to re-derive them.
    - ``neighbor_diffs``: mapping of sibling dep comp_id →
      short before/after summary describing how that neighbor
      has changed since this component was last regenerated.
      Empty on first-run comparch; populated on regen once Phase
      4 stage-by-stage is complete. For now the field exists as
      scaffolding.
    """

    component: Node
    component_techspec: str
    component_pubapi: str
    parent_resps: tuple[Node, ...]
    subresps: tuple[Node, ...]
    related_features: tuple[Node, ...]
    sibling_comp_ids: tuple[str, ...]
    sibling_comps: tuple[Node, ...]
    dep_pubapi_fragments: dict[str, str] = field(default_factory=dict)
    top_level_policy_candidates: tuple[Node, ...] = ()
    already_applied_policies: tuple[Node, ...] = ()
    neighbor_diffs: dict[str, str] = field(default_factory=dict)


def build_regen_context(session: Session, comp_id: str) -> RegenContext:
    """Assemble the regen-context bundle for a single top-level component.

    Strategy: start from :func:`queries.get_component_context`,
    which already bundles the component + fragments + parent resps
    + subresps + dep neighborhood. Then add Phase-4-specific
    extras via focused follow-up queries.

    Raises ``ValueError`` on unknown comp_id or non-component nodes
    (delegated to ``get_component_context``). Does not raise on
    missing fragments — empty strings are a normal state.
    """
    cc = get_component_context(session, comp_id)
    component = cc.node

    # Sibling top-level components (excluding this one).
    all_top_level = list_top_level_components(session, component.project_id)
    siblings = tuple(c for c in all_top_level if c.id != comp_id)
    sibling_ids = tuple(c.id for c in siblings)

    # Dep pubapi fragments: for each outbound dep, read its pubapi.
    # Missing fragment → empty string rather than KeyError, because
    # first-run comparch on a leaf sibling will find that target has
    # no minted pubapi yet (sysarch_mint writes skeletal content so
    # this is normally populated, but defensively tolerate missing).
    dep_pubapi: dict[str, str] = {}
    for dep_node in cc.outbound_deps:
        frag = session.get(Fragment, fragment_id(dep_node.id, FragmentKind.PUBAPI))
        dep_pubapi[dep_node.id] = frag.content if frag is not None else ""

    # Related features: walk backwards from parent_resps via
    # decomposition edges to find the feat_* nodes that decompose
    # into this component's top-level resps. A feature may appear
    # multiple times if more than one parent resp routes to it;
    # deduplicate on id.
    related_features = _collect_related_features(session, component.project_id, cc.parent_resps)

    # Top-level policy candidates: all policy_* with parent_id=None.
    top_level_policies = tuple(
        session.execute(
            select(Node)
            .where(
                Node.project_id == component.project_id,
                Node.tier == "policy",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )

    # Already-applied policies: join policy_application edges
    # where target_id is this component, resolving to the source
    # policy_* node. Excludes component-local policies that this
    # component minted itself — those appear via their parent_id
    # relationship and are handled separately at mint time.
    already_applied = _load_already_applied_policies(session, component.project_id, comp_id)

    return RegenContext(
        component=component,
        component_techspec=cc.techspec,
        component_pubapi=cc.pubapi,
        parent_resps=cc.parent_resps,
        subresps=cc.subresps,
        related_features=related_features,
        sibling_comp_ids=sibling_ids,
        sibling_comps=siblings,
        dep_pubapi_fragments=dep_pubapi,
        top_level_policy_candidates=top_level_policies,
        already_applied_policies=already_applied,
        neighbor_diffs={},  # Phase 4 first-run scaffolding
    )


def _collect_related_features(
    session: Session, project_id: str, parent_resps: tuple[Node, ...]
) -> tuple[Node, ...]:
    """Walk decomposition edges backwards from parent resps to features.

    For each top-level resp, find every ``decomposition`` edge
    whose target is the resp, then look up the source Node. Source
    nodes that are features (tier='feat') are kept; everything
    else (e.g. decomposition edges that target subresps) is
    filtered out. Deduplicate on feature id.
    """
    if not parent_resps:
        return ()
    resp_ids = [r.id for r in parent_resps]
    rows = session.execute(
        select(Node)
        .join(Edge, Edge.source_id == Node.id)
        .where(
            Edge.edge_type == "decomposition",
            Edge.target_id.in_(resp_ids),
            Node.tier == "feat",
            Node.project_id == project_id,
        )
        .order_by(Node.display_order.asc(), Node.id.asc())
    ).scalars()
    seen: set[str] = set()
    features: list[Node] = []
    for feat in rows:
        if feat.id in seen:
            continue
        seen.add(feat.id)
        features.append(feat)
    return tuple(features)


def _load_already_applied_policies(
    session: Session, project_id: str, comp_id: str
) -> tuple[Node, ...]:
    """Return policy_* nodes that already have a policy_application edge to comp_id."""
    rows = session.execute(
        select(Node)
        .join(Edge, Edge.source_id == Node.id)
        .where(
            Edge.edge_type == "policy_application",
            Edge.target_id == comp_id,
            Node.tier == "policy",
            Node.project_id == project_id,
        )
        .order_by(Node.id.asc())
    ).scalars()
    return tuple(rows)


def format_regen_context(ctx: RegenContext) -> dict[str, str]:
    """Render a :class:`RegenContext` as the kwargs dict the comparch
    prompt's ``render_user_prompt`` consumes.

    Returns a dict with keys matching the context kwargs of
    :func:`backend.graph.prompts.comparch.render_user_prompt`:

    - ``component_summary``
    - ``parent_resps_summary``
    - ``subresps_summary``
    - ``sibling_comps_summary``
    - ``dep_pubapi_summary``
    - ``top_level_policy_candidates_summary``
    - ``related_features_summary``

    Callers do ``**format_regen_context(ctx)`` into
    ``render_user_prompt`` and pass the regen/retry state
    (``prior_approved``, ``prior_pending``, ``feedback``,
    ``parse_error``) separately.

    Each returned value is either a populated markdown-ish block
    or an empty string when the corresponding section has nothing
    to show. The prompt's ``render_user_prompt`` already treats
    empty strings as "omit this section", so empty values produce
    a cleanly-empty prompt section rather than a header with no
    body.
    """
    return {
        "component_summary": _format_component_summary(ctx),
        "parent_resps_summary": _format_node_bullet_list(
            ctx.parent_resps,
            empty_fallback="(no top-level responsibilities assigned)",
        ),
        "subresps_summary": _format_node_bullet_list(
            ctx.subresps,
            empty_fallback="(no pre-minted subresponsibilities)",
        ),
        "sibling_comps_summary": _format_sibling_comps_summary(ctx.sibling_comps),
        "dep_pubapi_summary": _format_dep_pubapi_summary(
            ctx.sibling_comps, ctx.dep_pubapi_fragments
        ),
        "top_level_policy_candidates_summary": _format_policy_candidates_summary(
            ctx.top_level_policy_candidates, ctx.already_applied_policies
        ),
        "related_features_summary": _format_node_bullet_list(
            ctx.related_features,
            empty_fallback="",
        ),
    }


def _format_component_summary(ctx: RegenContext) -> str:
    """Render the component's own identity + role + api-intent as a header block.

    Pulls from the techspec + pubapi fragments that sysarch_mint
    populated with the component's role and api-intent paragraphs.
    On first-run comparch these are still the sysarch-time
    placeholders; on regen they're whatever the previous comparch
    pass wrote into them.
    """
    parts: list[str] = [f"**{ctx.component.name}**"]
    if ctx.component_techspec.strip():
        parts.append("")
        parts.append("*Role / techspec:*")
        parts.append(ctx.component_techspec.strip())
    if ctx.component_pubapi.strip():
        parts.append("")
        parts.append("*API intent:*")
        parts.append(ctx.component_pubapi.strip())
    return "\n".join(parts).rstrip()


def _format_node_bullet_list(nodes: tuple[Node, ...], *, empty_fallback: str) -> str:
    """Render a tuple of Nodes as ``- `id` **name**: content`` bullets."""
    if not nodes:
        return empty_fallback
    lines: list[str] = []
    for node in nodes:
        name = (node.name or "").strip() or "(unnamed)"
        content = (node.content or "").strip()
        if content:
            lines.append(f"- `{node.id}` **{name}**: {content}")
        else:
            lines.append(f"- `{node.id}` **{name}**")
    return "\n".join(lines)


def _format_sibling_comps_summary(siblings: tuple[Node, ...]) -> str:
    """Render sibling top-level components as an allowed-target list.

    Each entry shows the stable comp_* ID (the LLM echoes these
    verbatim into ``<dependencies>`` entries) plus the component
    name so the LLM can reason about what's available.
    """
    if not siblings:
        return "(no other top-level components — this is the only one)"
    lines: list[str] = []
    for comp in siblings:
        name = (comp.name or "").strip() or "(unnamed)"
        lines.append(f"- `{comp.id}` **{name}**")
    return "\n".join(lines)


def _format_dep_pubapi_summary(siblings: tuple[Node, ...], fragments: dict[str, str]) -> str:
    """Render the dep pubapi fragments as a per-sibling labeled block.

    Only shows entries from ``fragments`` that are non-empty —
    omits siblings whose pubapi hasn't been minted yet or whose
    comparch pass hasn't run. Returns an empty string if nothing
    has meaningful content; ``render_user_prompt`` then omits
    the whole section rather than producing an empty header.
    """
    if not fragments:
        return ""
    name_by_id = {c.id: (c.name or "").strip() or "(unnamed)" for c in siblings}
    sections: list[str] = []
    for comp_id, content in sorted(fragments.items()):
        stripped = content.strip()
        if not stripped:
            continue
        name = name_by_id.get(comp_id, "(unknown)")
        sections.append(f"## {name} (`{comp_id}`)\n\n{stripped}")
    return "\n\n".join(sections)


def _format_policy_candidates_summary(
    candidates: tuple[Node, ...], already_applied: tuple[Node, ...]
) -> str:
    """Render top-level policy candidates, marking the already-applied ones.

    The LLM reads this for context when reasoning about whether
    the component's subresponsibilities already fulfill any
    project-wide policies. The actual application pass runs
    after approval, but if the LLM notices "my subresps don't
    cover this policy's trigger at all", it can weight its
    decomposition to avoid structural problems later.

    Already-applied policies are prefixed with ``[applied]`` so
    the LLM knows not to re-apply them in the arch doc's own
    ``<policies>`` section — local policies are for new
    component-local invariants, not for re-stating top-level ones.
    """
    if not candidates:
        return ""
    applied_ids = {p.id for p in already_applied}
    lines: list[str] = []
    for policy in candidates:
        name = (policy.name or "").strip() or "(unnamed)"
        marker = "[applied] " if policy.id in applied_ids else ""
        # Policy content is an inline <policy> blob. Summarize by
        # showing just the id + name + marker; the LLM can read the
        # full blob in the content field if it matters.
        lines.append(f"- {marker}`{policy.id}` **{name}**")
    return "\n".join(lines)
