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
    domain_parents_of,
    get_component_context,
    list_subcomponents_of,
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

    Phase 5 subcomponent-specific fields (populated only when
    ``component`` has a non-null ``parent_id`` that points at
    another ``comp``):

    - ``parent_component``: the owning top-level comp Node, or
      ``None`` if ``component`` is itself top-level.
    - ``parent_techspec`` / ``parent_pubapi`` / ``parent_privapi``:
      the three fragment sections of the parent component that a
      subcomponent is allowed to read when producing its own
      arch doc. Private surface is subcomponent-only context —
      sibling top-level comps never see it.
    - ``sibling_subcomp_ids`` / ``sibling_subcomps``: same-parent
      sibling subcomponents. The subcomparch ``<dependencies>``
      section lets the LLM reference these by slugified alias.
    - ``sibling_subcomp_pubapi_fragments``: mapping of sibling
      subcomp id → pubapi content. Skeletal (role-derived) on
      first-run if the sibling's own subcomparch hasn't been
      generated yet; full content once it has.

    For top-level components these subcomponent-specific fields
    are all empty / None and ``sibling_comp_ids`` / ``sibling_comps``
    / ``dep_pubapi_fragments`` hold the top-level scoping
    (every other top-level comp + the subset this component
    depends on).

    For subcomponents, ``sibling_comp_ids`` / ``sibling_comps``
    are re-purposed to hold the **parent's sibling top-level
    comps** (the allowed real-id targets for the subcomparch
    ``<dependencies>`` section). ``dep_pubapi_fragments`` holds
    the parent's outbound dep pubapis (siblings-of-parent whose
    pubapi this subcomponent can see through the parent's own
    dep edges).
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
    # Phase 5 subcomponent-specific fields
    parent_component: Node | None = None
    parent_techspec: str = ""
    parent_pubapi: str = ""
    parent_privapi: str = ""
    sibling_subcomp_ids: tuple[str, ...] = ()
    sibling_subcomps: tuple[Node, ...] = ()
    sibling_subcomp_pubapi_fragments: dict[str, str] = field(default_factory=dict)

    # Project vocabulary — Phase 5.5. Every regen at every tier
    # sees the full project-level vocab plus the feature-local
    # vocab for every feature reachable from this component's
    # subtree via the decomposition walk. The stored content on
    # each vocab node is raw <vocab-entry> XML; the formatter
    # transforms it to prompt-friendly prose at render time.
    project_vocab: tuple[Node, ...] = ()
    feature_vocab: tuple[Node, ...] = ()

    # Domain-parent context — Phase 6. Populated when this
    # component (or, for a subcomponent, its parent top-level) is
    # presentational and has one or more ``domain_parent`` edges
    # to domain components. The comparch / subcomparch prompts
    # render these as a read-only "what you're presenting" block
    # so the LLM can align the presentational component's own
    # public surface with what the domain side already exposes.
    # For domain components these stay empty and the formatters
    # collapse to empty strings.
    #
    # Subcomponents of a presentational parent inherit the
    # grandparent-domain context through their parent — i.e. the
    # sub's regen context carries the same domain-parent bundle
    # as its presentational owner would.
    domain_parents: tuple[Node, ...] = ()
    domain_parent_techspecs: dict[str, str] = field(default_factory=dict)
    domain_parent_pubapis: dict[str, str] = field(default_factory=dict)

    # Phase 7 domain fan-in context. For each domain parent that
    # has a ``tier="fanin"`` child with non-empty content, maps
    # that parent's ``comp_*`` id to the serialized ``<fanin>``
    # block. The presentational comparch / subcomparch prompts
    # render this alongside the top-down techspec / pubapi as the
    # "as built" view, and the prompt frames the two views
    # side-by-side so the LLM can surface drift. Domain parents
    # without a fan-in yet (un-fanned-out domains, or domains
    # whose subs haven't approved impls yet) yield no entry —
    # the presentational prompt falls back to the raw pubapi
    # path unchanged. For domain comps themselves this stays
    # empty.
    domain_parent_fanins: dict[str, str] = field(default_factory=dict)

    # Referenced content — Phase 6.6. Every regen also sees the
    # rendered content of nodes this regen target has outgoing
    # ``reference`` edges to. The walker
    # (``references.referenced_content_for_node``) dispatches on
    # each target's tier to pull the right chunk (full content for
    # ref_*, pubapi fragment for comp_*, etc.), so the edge type
    # is source-tier-agnostic — any node can draw a ``reference``
    # edge to any other node. For targets without outgoing
    # reference edges this stays empty and the formatter renders
    # the sentinel "(no external references)" so the prompt
    # partition is always present and deterministic.
    referenced_content: dict[str, str] = field(default_factory=dict)


def build_regen_context(session: Session, comp_id: str) -> RegenContext:
    """Assemble the regen-context bundle for a single comp node.

    Auto-detects tier: if the component is top-level
    (``parent_id is None``), returns the Phase-4 comparch-shaped
    bundle (siblings = every other top-level comp, dep pubapis
    = the component's own outbound deps, no parent-specific
    fields).

    If the component is a subcomponent (``parent_id`` points at
    another ``comp``), returns a Phase-5 subcomparch-shaped
    bundle:

    - ``parent_component`` + three parent fragment sections
      (techspec / pubapi / privapi) are populated.
    - ``sibling_comp_ids`` / ``sibling_comps`` are the **parent's
      sibling top-level comps** (the allowed real-id targets for
      the subcomparch ``<dependencies>`` section).
    - ``dep_pubapi_fragments`` holds the parent's own outbound
      dep pubapis, so the subcomponent can see what its parent's
      ecosystem looks like.
    - ``sibling_subcomp_ids`` / ``sibling_subcomps`` +
      ``sibling_subcomp_pubapi_fragments`` hold same-parent
      siblings (the alias-addressable targets).

    Strategy: start from :func:`queries.get_component_context`,
    which already bundles the component + fragments + parent resps
    + subresps + dep neighborhood. Then add focused follow-up
    queries for the tier-specific context.

    Raises ``ValueError`` on unknown comp_id or non-component nodes
    (delegated to ``get_component_context``). Does not raise on
    missing fragments — empty strings are a normal state.
    """
    cc = get_component_context(session, comp_id)
    component = cc.node
    project_id = component.project_id

    is_subcomponent = component.parent_id is not None
    parent_component: Node | None = None
    parent_techspec = ""
    parent_pubapi = ""
    parent_privapi = ""
    sibling_subcomp_ids: tuple[str, ...] = ()
    sibling_subcomps: tuple[Node, ...] = ()
    sibling_subcomp_pubapi_fragments: dict[str, str] = {}

    if is_subcomponent:
        # Fetch the parent comp and verify the depth cap (defensive:
        # the reducer already enforces it at event-append time, so a
        # grandchild should never exist — but build_regen_context is
        # a read path and we want to surface corruption as a
        # ValueError, not a silent mis-population).
        assert component.parent_id is not None  # for mypy
        parent_node = session.get(Node, component.parent_id)
        if parent_node is None or parent_node.tier != "comp":
            raise ValueError(
                f"Subcomponent {comp_id!r} has parent_id "
                f"{component.parent_id!r} which is not a comp_* node"
            )
        if parent_node.parent_id is not None:
            raise ValueError(
                f"Subcomponent {comp_id!r} has a grandparent comp "
                f"{parent_node.parent_id!r}; the reducer's depth cap "
                "should prevent this."
            )
        parent_component = parent_node

        # Parent fragments: a subcomponent is allowed to read all
        # three of its parent's fragment sections (including
        # private-surface). Missing fragment → empty string.
        parent_techspec = _fragment_content(session, parent_node.id, FragmentKind.TECHSPEC)
        parent_pubapi = _fragment_content(session, parent_node.id, FragmentKind.PUBAPI)
        parent_privapi = _fragment_content(session, parent_node.id, FragmentKind.PRIVAPI)

        # Same-parent siblings (excluding self)
        all_subcomps = list_subcomponents_of(session, parent_node.id)
        siblings_same_parent = tuple(s for s in all_subcomps if s.id != comp_id)
        sibling_subcomps = siblings_same_parent
        sibling_subcomp_ids = tuple(s.id for s in siblings_same_parent)
        for sib in siblings_same_parent:
            sibling_subcomp_pubapi_fragments[sib.id] = _fragment_content(
                session, sib.id, FragmentKind.PUBAPI
            )

        # Parent's sibling top-level comps — the allowed real-id
        # targets for the subcomparch <dependencies> section.
        all_top_level = list_top_level_components(session, project_id)
        parent_siblings = tuple(c for c in all_top_level if c.id != parent_node.id)
        sibling_ids = tuple(c.id for c in parent_siblings)
        siblings = parent_siblings

        # Dep pubapi fragments: the subcomponent can see the
        # parent's own outbound deps (the parent's sibling
        # top-level comps it depends on). Read the parent's
        # outbound dep pubapis via its ComponentContext.
        parent_cc = get_component_context(session, parent_node.id)
        dep_pubapi: dict[str, str] = {}
        for dep_node in parent_cc.outbound_deps:
            dep_pubapi[dep_node.id] = _fragment_content(session, dep_node.id, FragmentKind.PUBAPI)
    else:
        # Top-level comp: sibling set is every other top-level,
        # dep pubapis are this component's own outbound deps.
        all_top_level = list_top_level_components(session, project_id)
        siblings = tuple(c for c in all_top_level if c.id != comp_id)
        sibling_ids = tuple(c.id for c in siblings)

        dep_pubapi = {}
        for dep_node in cc.outbound_deps:
            dep_pubapi[dep_node.id] = _fragment_content(session, dep_node.id, FragmentKind.PUBAPI)

    # Related features: walk backwards from parent_resps via
    # decomposition edges to find the feat_* nodes that decompose
    # into this component's top-level resps. A feature may appear
    # multiple times if more than one parent resp routes to it;
    # deduplicate on id. For subcomponents, parent_resps is empty
    # (subresps live under parent_id=comp_id and are not
    # decomposition-linked to features directly).
    related_features = _collect_related_features(session, project_id, cc.parent_resps)

    # Top-level policy candidates: all policy_* with parent_id=None.
    top_level_policies = tuple(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
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
    already_applied = _load_already_applied_policies(session, project_id, comp_id)

    # Project vocabulary: always include every project-level
    # vocab entry, plus the feature-local vocab for every feature
    # reachable from this component's subtree. The reachability
    # walk lives in vocabulary.reachable_vocab_for_node and
    # returns project-level + reachable-feature-local in one
    # ordered list. Split it into the two RegenContext fields
    # (project_vocab vs feature_vocab) so the formatter can
    # render them with distinct headers.
    from backend.graph import vocabulary as _vocab_module

    all_reachable_vocab = _vocab_module.reachable_vocab_for_node(session, project_id, comp_id)
    project_vocab_nodes = tuple(n for n in all_reachable_vocab if n.parent_id is None)
    feature_vocab_nodes = tuple(n for n in all_reachable_vocab if n.parent_id is not None)

    # Domain-parent context (Phase 6). For a presentational
    # top-level comp, look up its own domain_parent edges. For a
    # subcomponent whose parent top-level is presentational,
    # inherit the parent's domain-parent bundle so the sub sees
    # the same grandparent-domain context its owner would. For
    # domain comps at either tier, the bundle stays empty.
    domain_parent_lookup_source: str | None = None
    if is_subcomponent:
        if parent_component is not None and parent_component.kind == "presentational":
            domain_parent_lookup_source = parent_component.id
    else:
        if component.kind == "presentational":
            domain_parent_lookup_source = comp_id

    domain_parents_tuple: tuple[Node, ...] = ()
    domain_parent_techspec_map: dict[str, str] = {}
    domain_parent_pubapi_map: dict[str, str] = {}
    domain_parent_fanin_map: dict[str, str] = {}
    if domain_parent_lookup_source is not None:
        parent_rows = domain_parents_of(session, domain_parent_lookup_source)
        domain_parents_tuple = tuple(parent_rows)
        for parent in parent_rows:
            domain_parent_techspec_map[parent.id] = _fragment_content(
                session, parent.id, FragmentKind.TECHSPEC
            )
            domain_parent_pubapi_map[parent.id] = _fragment_content(
                session, parent.id, FragmentKind.PUBAPI
            )
            # Phase 7: if the domain parent has a fan-in child
            # with non-empty content, surface it alongside the
            # raw pubapi so the presentational regen can
            # compare contract (pubapi) against built reality
            # (fan-in). Missing / empty fan-in leaves the
            # pubapi path unchanged — un-fanned-out domain
            # parents and domain parents whose subs haven't
            # approved impls yet both fall through here.
            fanin_content = _fanin_content_for_comp(session, parent.id)
            if fanin_content:
                domain_parent_fanin_map[parent.id] = fanin_content

    # Referenced content (Phase 6.6): pull every node this regen
    # target has an outgoing ``reference`` edge to. The walker is
    # source-tier-agnostic and dispatches on the target's tier.
    from backend.graph import references as _references_module

    referenced_content_map = _references_module.referenced_content_for_node(
        session, project_id, comp_id
    )

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
        parent_component=parent_component,
        parent_techspec=parent_techspec,
        parent_pubapi=parent_pubapi,
        parent_privapi=parent_privapi,
        sibling_subcomp_ids=sibling_subcomp_ids,
        sibling_subcomps=sibling_subcomps,
        sibling_subcomp_pubapi_fragments=sibling_subcomp_pubapi_fragments,
        project_vocab=project_vocab_nodes,
        feature_vocab=feature_vocab_nodes,
        domain_parents=domain_parents_tuple,
        domain_parent_techspecs=domain_parent_techspec_map,
        domain_parent_pubapis=domain_parent_pubapi_map,
        domain_parent_fanins=domain_parent_fanin_map,
        referenced_content=referenced_content_map,
    )


def build_fanin_synthesis_context(
    session: Session,
    owner_comp_id: str,
) -> dict[str, object]:
    """Assemble the input bundle the fan-in prompt consumes.

    Phase 7 counterpart to :func:`build_regen_context`. Unlike
    that helper, fan-in synthesis is bottom-up: it doesn't read
    the owner comp's own techspec / pubapi. The inputs are:

    - ``owner_summary``: ``name (comp_id)`` — a handle, not a
      spec. The fan-in prompt explicitly instructs the LLM not
      to see the owning comp's design intent.
    - ``sub_pubapi_fragments``: ordered list of ``{"sub_name",
      "sub_id", "pubapi"}`` dicts, one per direct subcomponent
      of the owning comp. Pubapi content is the sub's pubapi
      fragment (subcomparch-produced).
    - ``impl_contents``: ordered list of ``{"owner_name",
      "owner_id", "content"}`` dicts, one per ``tier="impl"``
      node under the owning comp's subtree. Ordered by a
      deterministic DFS so reproducibility is stable across
      regens.
    - ``vocab_summary`` / ``referenced_content_summary``: shared
      cross-cutting context rendered the same way every other
      tier sees them.

    Raises ``ValueError`` if ``owner_comp_id`` does not resolve
    to a ``comp_*`` node in the session.
    """
    owner = session.get(Node, owner_comp_id)
    if owner is None:
        raise ValueError(f"build_fanin_synthesis_context: owner comp {owner_comp_id!r} not found")
    if owner.tier != "comp":
        raise ValueError(
            f"build_fanin_synthesis_context: owner {owner_comp_id!r} is "
            f"tier={owner.tier!r}, expected 'comp'"
        )

    # Direct subs, ordered deterministically.
    subs = list(list_subcomponents_of(session, owner_comp_id))

    sub_pubapi_fragments: list[dict[str, str]] = []
    for sub in subs:
        sub_pubapi_fragments.append(
            {
                "sub_name": sub.name or "",
                "sub_id": sub.id,
                "pubapi": _fragment_content(session, sub.id, FragmentKind.PUBAPI),
            }
        )

    # Impl contents: walk the subtree via DFS. For fanned-out
    # domain comps, the impls live one-per-sub under each sub.
    # For the (theoretical, not currently reachable via
    # comparch_mint for fanned-out comps) case of a second-level
    # impl, we'd pick it up via DFS — but the depth cap means
    # that can't happen today. Using DFS keeps the walk
    # tier-shape-agnostic.
    impl_contents: list[dict[str, str]] = []
    stack: list[Node] = [owner]
    while stack:
        current = stack.pop()
        children = list(
            session.execute(
                select(Node)
                .where(Node.parent_id == current.id)
                .order_by(Node.display_order.asc(), Node.id.asc())
            ).scalars()
        )
        # Push in reverse so the visit order matches display_order.
        for child in reversed(children):
            if child.tier == "impl":
                impl_contents.append(
                    {
                        "owner_name": current.name or "",
                        "owner_id": current.id,
                        "content": child.content or "",
                    }
                )
            elif child.tier == "comp":
                stack.append(child)

    # Build a throwaway RegenContext-like shape only for the
    # vocab + referenced-content summaries that share renderers
    # with other tiers. We don't need the full RegenContext
    # here, but the two render helpers take the RegenContext's
    # ``component`` field to resolve the session, so we bind
    # ``owner`` directly.
    owner_summary = f"**{owner.name or '(unnamed)'}** (`{owner.id}`)"

    from backend.graph import references as _references_module
    from backend.graph import vocabulary as _vocab_module

    all_reachable_vocab = _vocab_module.reachable_vocab_for_node(
        session, owner.project_id, owner_comp_id
    )
    project_vocab_nodes = tuple(n for n in all_reachable_vocab if n.parent_id is None)
    feature_vocab_nodes = tuple(n for n in all_reachable_vocab if n.parent_id is not None)
    feature_name_map = _vocab_module._build_feature_name_map(session, feature_vocab_nodes)
    vocab_summary = _vocab_module.format_vocab_summary(
        project_vocab_nodes,
        feature_vocab_nodes,
        feature_names=feature_name_map,
    )

    referenced_content_map = _references_module.referenced_content_for_node(
        session, owner.project_id, owner_comp_id
    )
    referenced_content_summary = _references_module.format_referenced_content_summary(
        referenced_content_map
    )

    return {
        "owner_summary": owner_summary,
        "sub_pubapi_fragments": sub_pubapi_fragments,
        "impl_contents": impl_contents,
        "vocab_summary": vocab_summary,
        "referenced_content_summary": referenced_content_summary,
    }


def _fanin_content_for_comp(session: Session, comp_id: str) -> str:
    """Return the ``tier="fanin"`` child's content for ``comp_id``, or empty.

    Fan-in is minted once per fanned-out domain comp (see
    :mod:`backend.graph.handlers.comparch_mint`); the row exists
    with ``content=""`` from mint time and gets its real content
    written by the fan-in generation handler on the first impl
    approval beneath the comp. Callers use empty-string as the
    "no fan-in available" signal.
    """
    row = session.execute(
        select(Node).where(
            Node.parent_id == comp_id,
            Node.tier == "fanin",
        )
    ).scalar_one_or_none()
    return (row.content or "") if row is not None else ""


def _fragment_content(session: Session, owner_id: str, kind: FragmentKind) -> str:
    """Read a fragment's content, returning empty string if missing."""
    frag = session.get(Fragment, fragment_id(owner_id, kind))
    return frag.content if frag is not None else ""


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
    - ``parent_resps_summary`` (with bracketed feat-id lists)
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
        "parent_resps_summary": _format_parent_resps_with_feats(ctx),
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
        "vocab_summary": _render_vocab_summary_from_ctx(ctx),
        "domain_parent_surface": _render_domain_parent_surface_for_comparch(ctx),
        "referenced_content_summary": _render_referenced_content_from_ctx(ctx),
    }


def _render_domain_parent_surface_for_comparch(ctx: RegenContext) -> str:
    """Render the Phase 6 domain-parent context block for comparch.

    Delegates to
    :func:`backend.graph.prompts.comparch.format_domain_parent_surface`
    via a local import to keep the import direction
    ``prompts -> regen_context`` clean (mirrors the
    ``_render_vocab_summary_from_ctx`` pattern above). Phase 7
    threads the per-parent fan-in content through alongside
    techspec / pubapi so the presentational prompt can surface
    drift between the two.
    """
    from backend.graph.prompts.comparch import format_domain_parent_surface

    return format_domain_parent_surface(
        ctx.domain_parents,
        ctx.domain_parent_techspecs,
        ctx.domain_parent_pubapis,
        ctx.domain_parent_fanins,
    )


def format_regen_context_for_sub(ctx: RegenContext) -> dict[str, str]:
    """Render a subcomponent :class:`RegenContext` as subcomparch kwargs.

    Mirror of :func:`format_regen_context` for the Phase 5
    subcomparch prompt at
    :mod:`backend.graph.prompts.subcomparch`. The two formatters
    are deliberately separate functions rather than a single
    tier-switching one because the subcomparch prompt's
    ``render_user_prompt`` takes a different set of kwargs
    (``parent_component_summary``, ``sibling_subcomps_summary``,
    etc.) from the comparch prompt's.

    Returns a dict with keys matching the subcomparch
    ``render_user_prompt`` signature:

    - ``subcomponent_summary``
    - ``parent_component_summary``
    - ``subresps_summary``
    - ``sibling_subcomps_summary``
    - ``parent_sibling_comps_summary``
    - ``dep_pubapi_summary``

    Caller does ``**format_regen_context_for_sub(ctx)`` into
    ``render_user_prompt`` and passes the regen/retry state
    separately. Requires ``ctx.parent_component`` to be non-None
    — raises ``ValueError`` if called on a top-level comp context.
    """
    if ctx.parent_component is None:
        raise ValueError(
            "format_regen_context_for_sub called on a top-level "
            "component context; use format_regen_context instead."
        )
    return {
        "subcomponent_summary": _format_subcomponent_summary(ctx),
        "parent_component_summary": _format_parent_component_summary(ctx),
        # For a subcomp, what we want is the parent resps + feat
        # slices the parent comparch's <owns> block claimed for this
        # sub. Walked from incoming decomposition edges in
        # _format_subcomp_owns_summary.
        "owns_summary": _format_subcomp_owns_summary(ctx),
        "sibling_subcomps_summary": _format_sibling_subcomps_summary(
            ctx.sibling_subcomps,
            ctx.sibling_subcomp_pubapi_fragments,
        ),
        "parent_sibling_comps_summary": _format_sibling_comps_summary(ctx.sibling_comps),
        "dep_pubapi_summary": _format_dep_pubapi_summary(
            ctx.sibling_comps, ctx.dep_pubapi_fragments
        ),
        "vocab_summary": _render_vocab_summary_from_ctx(ctx),
        "domain_parent_surface": _render_domain_parent_surface_for_sub(ctx),
        "referenced_content_summary": _render_referenced_content_from_ctx(ctx),
    }


def format_regen_context_for_impl(ctx: RegenContext) -> dict[str, str]:
    """Render a :class:`RegenContext` as impl prompt kwargs.

    Phase 8 counterpart to :func:`format_regen_context` and
    :func:`format_regen_context_for_sub`. Works for both
    un-fanned-out top-level comps (where ``ctx.parent_component``
    is None) and subcomponents (where it's the owning comp).

    Returns a dict with keys matching
    :func:`backend.graph.prompts.impl.render_user_prompt`:

    - ``owner_summary``: the leaf's own name + role + pubapi /
      privapi summary
    - ``parent_summary``: the owning parent component's techspec
      + pubapi + privapi. Empty string for un-fanned-out
      top-level impls (the leaf IS the top-level comp).
    - ``dep_pubapi_summary``: public surfaces of the leaf's
      allowed deps (reused from the existing dep summary).
    - ``vocab_summary`` / ``referenced_content_summary``: shared
      with every other tier that takes them.

    Impl has no domain-parent concern (that lives at the
    comparch level), so the domain-parent surface is intentionally
    not surfaced here.
    """
    return {
        "owner_summary": _format_impl_owner_summary(ctx),
        "parent_summary": _format_impl_parent_summary(ctx),
        "dep_pubapi_summary": _format_dep_pubapi_summary(
            ctx.sibling_comps, ctx.dep_pubapi_fragments
        ),
        "vocab_summary": _render_vocab_summary_from_ctx(ctx),
        "referenced_content_summary": _render_referenced_content_from_ctx(ctx),
    }


def _format_impl_owner_summary(ctx: RegenContext) -> str:
    """Render the impl's owning leaf identity + its own fragments.

    For a subcomponent impl, ``ctx.component`` is the subcomponent;
    its techspec / pubapi / privapi fragments describe the
    subcomparch-level view (what the subcomponent exposes to
    siblings and what it keeps private). For an un-fanned-out
    top-level impl, ``ctx.component`` is the top-level comp; its
    comparch-level fragments describe the same but at the
    top-level scope.
    """
    parts: list[str] = [f"**{ctx.component.name}** (`{ctx.component.id}`)"]
    if ctx.component_techspec.strip():
        parts.append("")
        parts.append("*Technical specification:*")
        parts.append(ctx.component_techspec.strip())
    if ctx.component_pubapi.strip():
        parts.append("")
        parts.append("*Public surface:*")
        parts.append(ctx.component_pubapi.strip())
    from backend.graph.fragments import FragmentKind

    # The leaf's privapi is what its impl is allowed to see about
    # its own internal helpers. Only populated when the node has
    # a privapi fragment (subcomponent or comparch leaf post-mint).
    session = _session_from_node(ctx.component)
    if session is not None:
        privapi = _fragment_content(session, ctx.component.id, FragmentKind.PRIVAPI)
        if privapi.strip():
            parts.append("")
            parts.append("*Private surface:*")
            parts.append(privapi.strip())
    return "\n".join(parts).rstrip()


def _format_impl_parent_summary(ctx: RegenContext) -> str:
    """Render the owning parent component's fragments for a subcomponent impl.

    Returns empty string for un-fanned-out top-level impls (where
    the leaf IS the top-level and has no parent component). For
    subcomponent impls, returns techspec + pubapi + privapi in a
    labeled block — identical to
    :func:`_format_parent_component_summary` but phrased for the
    impl reader rather than the subcomparch reader.
    """
    if ctx.parent_component is None:
        return ""
    parts: list[str] = [f"**{ctx.parent_component.name}** (`{ctx.parent_component.id}`)"]
    if ctx.parent_techspec.strip():
        parts.append("")
        parts.append("*Parent technical specification:*")
        parts.append(ctx.parent_techspec.strip())
    if ctx.parent_pubapi.strip():
        parts.append("")
        parts.append("*Parent public surface:*")
        parts.append(ctx.parent_pubapi.strip())
    if ctx.parent_privapi.strip():
        parts.append("")
        parts.append("*Parent private surface:*")
        parts.append(ctx.parent_privapi.strip())
    return "\n".join(parts).rstrip()


def _render_domain_parent_surface_for_sub(ctx: RegenContext) -> str:
    """Render the Phase 6 domain-parent context block for subcomparch.

    Mirrors :func:`_render_domain_parent_surface_for_comparch`, but
    delegates to the subcomparch-side thin wrapper so the
    framing-prose side of the rendering stays with the prompt
    module that owns it. The actual per-parent layout is shared
    with comparch via the wrapper, including the Phase 7 fan-in
    thread-through.
    """
    from backend.graph.prompts.subcomparch import format_domain_parent_surface_for_sub

    return format_domain_parent_surface_for_sub(
        ctx.domain_parents,
        ctx.domain_parent_techspecs,
        ctx.domain_parent_pubapis,
        ctx.domain_parent_fanins,
    )


def _render_referenced_content_from_ctx(ctx: RegenContext) -> str:
    """Render the Phase 6.6 referenced-content partition.

    Delegates to ``references.format_referenced_content_summary``
    so comparch / subcomparch / requirements / sysarch / subreqs
    / policy-application all share one renderer. The summary
    collapses to the sentinel ``"(no external references)"`` when
    ``ctx.referenced_content`` is empty, which keeps the prompt
    partition visible but minimal.
    """
    from backend.graph import references

    return references.format_referenced_content_summary(ctx.referenced_content)


def _render_vocab_summary_from_ctx(ctx: RegenContext) -> str:
    """Render the vocab context partition for comparch / subcomparch.

    The RegenContext already carries the reachable vocab nodes in
    ``project_vocab`` + ``feature_vocab``. Resolving feature names
    for prompt-friendly rendering needs the bound session, which
    we get from any node in the context — ``ctx.component`` is
    always present. Delegates the actual formatting to
    ``vocabulary.format_vocab_summary`` so comparch / subcomparch
    / requirements / sysarch / subreqs all share one renderer.
    """
    from sqlalchemy.orm import object_session

    from backend.graph import vocabulary

    session = object_session(ctx.component)
    feature_names: dict[str, str] = {}
    if session is not None:
        feature_names = vocabulary._build_feature_name_map(session, ctx.feature_vocab)
    return vocabulary.format_vocab_summary(
        ctx.project_vocab,
        ctx.feature_vocab,
        feature_names=feature_names,
    )


def _format_subcomponent_summary(ctx: RegenContext) -> str:
    """Render the subcomponent's own identity + seeded fragments.

    Pulls from the subcomponent's techspec + pubapi fragments,
    which comparch_mint seeded from the parent's decomposition
    entry (``role`` → techspec, ``api-intent`` → pubapi) at Phase
    4 time. On first-run subcomparch these are the skeletal
    seeds; on regen they're whatever the previous subcomparch
    pass wrote into them.

    The header line carries both the human-readable name and the
    stable ``comp_*`` id — same rationale as
    :func:`_format_component_summary`.
    """
    parts: list[str] = [f"**{ctx.component.name}** (`{ctx.component.id}`)"]
    if ctx.component_techspec.strip():
        parts.append("")
        parts.append("*Role (from parent comparch):*")
        parts.append(ctx.component_techspec.strip())
    if ctx.component_pubapi.strip():
        parts.append("")
        parts.append("*Intended API (from parent comparch):*")
        parts.append(ctx.component_pubapi.strip())
    return "\n".join(parts).rstrip()


def _format_parent_component_summary(ctx: RegenContext) -> str:
    """Render the owning top-level parent component's identity + fragments.

    Subcomponents are allowed to read all three parent fragment
    sections: techspec (root tech choices), public surface (what
    callers see), and private surface (internal helpers scoped
    to the parent's subtree). The subcomparch prompt uses all
    three to ground its own sections in what the parent already
    committed to.
    """
    if ctx.parent_component is None:
        return "(no parent component — bug: this should only be called for subcomponents)"
    parts: list[str] = [f"**{ctx.parent_component.name}** (`{ctx.parent_component.id}`)"]
    if ctx.parent_techspec.strip():
        parts.append("")
        parts.append("*Parent technical specification:*")
        parts.append(ctx.parent_techspec.strip())
    if ctx.parent_pubapi.strip():
        parts.append("")
        parts.append("*Parent public surface:*")
        parts.append(ctx.parent_pubapi.strip())
    if ctx.parent_privapi.strip():
        parts.append("")
        parts.append("*Parent private surface:*")
        parts.append(ctx.parent_privapi.strip())
    return "\n".join(parts).rstrip()


def _format_parent_resps_with_feats(ctx: RegenContext) -> str:
    """Render the component's parent resps with their feat-tag lists.

    Each parent resp is rendered as ``- `resp_xxx` **Name** [feat_aaa, feat_bbb]``
    so the comparch LLM can echo both the resp id and per-resp feat
    ids into the per-subcomp ``<owns>`` block. Walks incoming
    decomposition edges from feat_* sources to compute each parent
    resp's in-scope feat set.
    """
    if not ctx.parent_resps:
        return "(no top-level responsibilities assigned)"
    session = _session_from_node(ctx.component)
    feats_by_resp: dict[str, list[Node]] = {r.id: [] for r in ctx.parent_resps}
    if session is not None:
        feat_edge_rows = list(
            session.execute(
                select(Edge.target_id, Node)
                .join(Node, Node.id == Edge.source_id)
                .where(
                    Edge.edge_type == "decomposition",
                    Edge.target_id.in_({r.id for r in ctx.parent_resps}),
                    Node.tier == "feat",
                )
                .order_by(Node.display_order.asc(), Node.id.asc())
            )
        )
        for resp_id, feat_node in feat_edge_rows:
            feats_by_resp.setdefault(resp_id, []).append(feat_node)
    lines: list[str] = []
    for resp in ctx.parent_resps:
        rid = resp.id
        name = (resp.name or "").strip() or "(unnamed)"
        feat_ids = [f.id for f in feats_by_resp.get(rid, [])]
        suffix = f" [{', '.join(feat_ids)}]" if feat_ids else " []"
        lines.append(f"- `{rid}` **{name}**{suffix}")
    return "\n".join(lines)


def _format_subcomp_owns_summary(ctx: RegenContext) -> str:
    """Render the parent resps + feat-slice this subcomp owns.

    Walks incoming ``decomposition`` edges to ``ctx.component.id``
    where the source is a parent resp (``tier="resp"``,
    ``parent_id=None``) or a feat (``tier="feat"``). The owning
    parent comp's comparch produced these edges from each subcomp's
    ``<owns>`` block at mint time.

    Returns a per-claim bullet list:

        - `resp_payment01` **Payment Collection** (owns feats: feat_card_v01, feat_3ds_chal01)
        - `resp_invoice02` **Invoicing** (owns whole resp)

    Empty fallback when the subcomp claims nothing (foundation /
    plumbing).
    """
    session = _session_from_node(ctx.component)
    if session is None:
        return "(ownership unavailable without a DB session)"

    # Owned parent resps (top-level resps this sub claims).
    resp_rows = list(
        session.execute(
            select(Node)
            .join(Edge, Edge.source_id == Node.id)
            .where(
                Edge.edge_type == "decomposition",
                Edge.target_id == ctx.component.id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )
    if not resp_rows:
        return "(this subcomponent does not anchor any parent responsibility)"

    # Owned feats (feat_* sources of decomposition edges into this sub).
    feat_rows = list(
        session.execute(
            select(Node)
            .join(Edge, Edge.source_id == Node.id)
            .where(
                Edge.edge_type == "decomposition",
                Edge.target_id == ctx.component.id,
                Node.tier == "feat",
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )
    owned_feat_ids: set[str] = {f.id for f in feat_rows}

    # For each owned resp, the feat-slice intersection: which feats
    # tagged on the resp does this sub also claim?
    feats_by_resp: dict[str, list[str]] = {}
    if owned_feat_ids and resp_rows:
        feat_edge_rows = list(
            session.execute(
                select(Edge.target_id, Edge.source_id)
                .where(
                    Edge.edge_type == "decomposition",
                    Edge.target_id.in_({r.id for r in resp_rows}),
                    Edge.source_id.in_(owned_feat_ids),
                )
            )
        )
        for resp_id, feat_id in feat_edge_rows:
            feats_by_resp.setdefault(resp_id, []).append(feat_id)

    lines: list[str] = []
    for resp in resp_rows:
        rid = resp.id
        name = (resp.name or "").strip() or "(unnamed)"
        slice_ids = sorted(feats_by_resp.get(rid, []))
        if slice_ids:
            tag = f"(owns feats: {', '.join(slice_ids)})"
        else:
            tag = "(owns whole resp — no feat-slice narrowing)"
        lines.append(f"- `{rid}` **{name}** {tag}")
    return "\n".join(lines)


def _session_from_node(node: Node) -> Session | None:
    """Return the Session bound to an ORM row, or None if detached."""
    from sqlalchemy.orm import object_session

    return object_session(node)


def _format_sibling_subcomps_summary(
    siblings: tuple[Node, ...],
    pubapi_fragments: dict[str, str],
) -> str:
    """Render same-parent sibling subcomponents as a comp_* ID allowlist.

    Each entry shows the sibling's real ``comp_*`` ID (the value
    the LLM echoes verbatim as ``<dep to="..."/>``) and its
    display name. The alias indirection was removed — sibling
    subcomponents already have stable IDs at subcomparch
    generation time because they were minted by the parent's
    comparch_mint before this generation runs.

    Includes the sibling's pubapi fragment as nested context when
    it has content (skeletal seed or full arch doc — either way
    the LLM can ground its dep choices in what the sibling
    actually exposes). Empty pubapi siblings omit the nested
    block to keep the prompt tight.
    """
    if not siblings:
        return "(no same-parent sibling subcomponents — this is the only sub under its parent)"
    lines: list[str] = []
    for sib in siblings:
        name = (sib.name or "").strip() or "(unnamed)"
        lines.append(f"- `{sib.id}` **{name}**")
        body = (pubapi_fragments.get(sib.id) or "").strip()
        if body:
            # Indent the body so it's clearly nested under the bullet
            indented = "\n".join(f"  {line}" for line in body.splitlines())
            lines.append(indented)
    return "\n".join(lines)


def _format_component_summary(ctx: RegenContext) -> str:
    """Render the component's own identity + role + api-intent as a header block.

    Pulls from the techspec + pubapi fragments that sysarch_mint
    populated with the component's role and api-intent paragraphs.
    On first-run comparch these are still the sysarch-time
    placeholders; on regen they're whatever the previous comparch
    pass wrote into them.

    The header line carries both the human-readable name and the
    stable ``comp_*`` id so the LLM can reference the target
    unambiguously in prose, and so tests and debug tools can
    locate the "this is the current target" prompt by searching
    for the id rather than the name.
    """
    parts: list[str] = [f"**{ctx.component.name}** (`{ctx.component.id}`)"]
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
