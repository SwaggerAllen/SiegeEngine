"""Project vocabulary node helpers.

Vocabulary entries are ``vocab_*`` nodes — a first-class node tier
whose purpose is to carry project-specific term definitions so the
LLM's generic priors don't silently substitute generic meanings
during per-node regeneration. See
``docs/architecture/v2-rearchitecture.md`` §Project vocabulary for
the full rationale.

Each ``vocab_*`` node's ``content`` field holds a parseable
``<vocab-entry>`` XML block with three children in fixed order:
``<definition>`` (required), ``<disambiguation>`` (optional), and
``<see-also>`` (optional, containing ``<ref name="..."/>`` or
``<ref to="vocab_..."/>`` children). The grammar is validated at
authoring time; this module doesn't parse it — it just looks up
vocab nodes by the same kind of queries the rest of the codebase
uses to look up features, responsibilities, and so on. Callers
that need structured access to a vocab entry's content should run
``validate_vocabulary`` from ``backend.graph.parsers.validators``
over the entry's ``Node.content`` string.

Scoping lives on ``Node.parent_id``:
    * ``None`` — project-level; every regen at every tier sees it.
    * a ``feat_*`` id — feature-local; only regens reachable from
      that feature via the decomposition walk see it.

The reducer (``backend.graph.reducer._enforce_vocab_parent_constraint``)
rejects any attempt to parent a vocab node under a non-feature
node, so callers here can assume ``parent_id`` is either ``None``
or a ``feat_*`` id without re-checking.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.node import Edge, Node

VOCAB_TIER = "vocab"


def list_project_vocab(session: Session, project_id: str) -> list[Node]:
    """Return every project-level vocab node (``parent_id`` is NULL)."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
                Node.parent_id.is_(None),
            )
            .order_by(Node.name.asc())
        ).scalars()
    )


def list_feature_vocab(session: Session, project_id: str, feat_id: str) -> list[Node]:
    """Return every vocab node scoped to one specific feature."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
                Node.parent_id == feat_id,
            )
            .order_by(Node.name.asc())
        ).scalars()
    )


def list_all_vocab(session: Session, project_id: str) -> list[Node]:
    """Return every vocab node in the project, regardless of scope.

    Ordered by scope (project-level first, then feature-local grouped
    by owning feature id) and then by name.
    """
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
            )
            .order_by(
                Node.parent_id.asc().nullsfirst(),
                Node.name.asc(),
            )
        ).scalars()
    )


def vocab_by_id(session: Session, vocab_id: str) -> Node | None:
    """Return the vocab node with ``id == vocab_id``, or ``None``.

    Does not check that the id actually starts with ``vocab_`` — the
    caller is responsible for passing a vocab id, and the reducer's
    tier enforcement guarantees every row with ``tier == 'vocab'``
    carries a ``vocab_*`` id.
    """
    node = session.get(Node, vocab_id)
    if node is None or node.tier != VOCAB_TIER:
        return None
    return node


def vocab_by_name(
    session: Session,
    project_id: str,
    name: str,
    *,
    parent_id: str | None = None,
) -> Node | None:
    """Look up a vocab entry by its term name within a specific scope.

    Returns ``None`` if no entry with that name exists at the given
    scope. Scope is part of the key because the same term name is
    legal at both project level and feature level simultaneously — a
    ``billing.tranche`` feature-local entry and a project-level
    ``tranche`` can coexist, and callers need to disambiguate by
    scope.
    """
    if parent_id is None:
        return session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == VOCAB_TIER,
                Node.name == name,
                Node.parent_id.is_(None),
            )
        ).scalar_one_or_none()
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == VOCAB_TIER,
            Node.name == name,
            Node.parent_id == parent_id,
        )
    ).scalar_one_or_none()


def reachable_vocab_for_node(session: Session, project_id: str, node_id: str) -> list[Node]:
    """Return every vocab entry relevant to a node's regen prompt.

    The set is: every project-level vocab entry (always included),
    plus every feature-local vocab entry parented to a feature the
    target node's subtree serves. Reachability is computed by
    walking the decomposition graph from the target node back to
    features — the same walk the regen context assembly already
    does for the "related features" partition.

    The walk is conservative: it traverses ``decomposition`` edges in
    reverse (``resp → feat``) from the target and from every ancestor
    in the target's parent chain (for ``comp_*`` nodes, this means
    walking up through subcomponents to the top-level component, then
    following the assigned-responsibility edges back to the features
    that route through it). Duplicates are removed. If the target is
    itself a feature, it's treated as its own reachable feature.

    Ordering of returned nodes: project-level entries first (sorted
    by name), then feature-local entries grouped by owning feature
    id and sorted by name within each group. Callers that render
    these into prompts rely on stable order so the rendered
    vocabulary summary is deterministic across regens.
    """
    target = session.get(Node, node_id)
    if target is None or target.project_id != project_id:
        return list_project_vocab(session, project_id)

    reachable_feat_ids: set[str] = set()

    if target.tier == "feat":
        reachable_feat_ids.add(target.id)
    else:
        # Walk up through the parent chain first to find the
        # owning top-level comp (or the target itself if it's
        # already a feat / resp / other).
        seed_ids: set[str] = {target.id}
        cursor: Node | None = target
        while cursor is not None and cursor.parent_id is not None:
            parent = session.get(Node, cursor.parent_id)
            if parent is None or parent.project_id != project_id:
                break
            seed_ids.add(parent.id)
            cursor = parent

        # From each seed, walk decomposition edges backwards until
        # we hit feat_* nodes. A breadth-first walk keeps it simple
        # and bounded; in practice the graph is small.
        frontier: set[str] = set(seed_ids)
        visited: set[str] = set()
        while frontier:
            next_frontier: set[str] = set()
            for nid in frontier:
                if nid in visited:
                    continue
                visited.add(nid)
                if nid.startswith("feat_"):
                    reachable_feat_ids.add(nid)
                    continue
                # Pull all decomposition edges pointing AT this node
                # and add their sources to the frontier.
                source_ids = list(
                    session.execute(
                        select(Edge.source_id).where(
                            Edge.project_id == project_id,
                            Edge.edge_type == "decomposition",
                            Edge.target_id == nid,
                        )
                    ).scalars()
                )
                for sid in source_ids:
                    if sid not in visited:
                        next_frontier.add(sid)
            frontier = next_frontier

    # Assemble the result: project-level first, then feature-local
    # for each reachable feature.
    result: list[Node] = list_project_vocab(session, project_id)
    for feat_id in sorted(reachable_feat_ids):
        result.extend(list_feature_vocab(session, project_id, feat_id))
    return result


# ── Prompt-friendly rendering ────────────────────────────────


def render_vocab_summary_for_node(session: Session, project_id: str, node_id: str) -> str:
    """Build the vocab context string for a regen prompt targeting a single node.

    Pulls every project-level vocab entry plus every feature-
    local entry reachable from the target via the decomposition
    walk, then renders them as prompt-friendly prose. Used by
    the component / subcomponent / subreqs / policy-application
    tiers where the regen is scoped to a single component
    subtree.
    """
    all_reachable = reachable_vocab_for_node(session, project_id, node_id)
    project = tuple(n for n in all_reachable if n.parent_id is None)
    feature = tuple(n for n in all_reachable if n.parent_id is not None)
    feature_names = _build_feature_name_map(session, feature)
    return format_vocab_summary(project, feature, feature_names=feature_names)


def render_vocab_summary_all(session: Session, project_id: str) -> str:
    """Build the vocab context string including every vocab entry in the project.

    Used by the top-level resolver tiers (``reqs``, ``sysarch``)
    where the regen reasons across the entire feature set at
    once and the LLM should see every defined term, regardless
    of which feature owns it.
    """
    all_nodes = list_all_vocab(session, project_id)
    project = tuple(n for n in all_nodes if n.parent_id is None)
    feature = tuple(n for n in all_nodes if n.parent_id is not None)
    feature_names = _build_feature_name_map(session, feature)
    return format_vocab_summary(project, feature, feature_names=feature_names)


def _build_feature_name_map(session: Session, feature_vocab: tuple[Node, ...]) -> dict[str, str]:
    """Return ``{feat_id: feature_name}`` for every parent referenced."""
    parent_ids = {n.parent_id for n in feature_vocab if n.parent_id is not None}
    result: dict[str, str] = {}
    for parent_id in parent_ids:
        parent_node = session.get(Node, parent_id)
        if parent_node is not None and parent_node.name:
            result[parent_id] = parent_node.name
    return result


def format_vocab_summary(
    project_vocab: tuple[Node, ...],
    feature_vocab: tuple[Node, ...],
    *,
    feature_names: dict[str, str] | None = None,
) -> str:
    """Transform vocab nodes' stored ``<vocab-entry>`` XML into prompt prose.

    Storage is XML so future additions (cross-reference edge
    emission, structured UI rendering, new grammar fields) have
    something to work on. The prompt format is prose because
    the LLM doesn't need raw tags — prompt tokens are too
    expensive to spend on markup the model will ignore.

    Output shape:

        # Project vocabulary

        **term-name** (project-level)
        Definition: ...
        Disambiguation: ... [if present]
        See also: term1, term2 [if present]

        # Feature vocabulary

        **local-term** (from feature: Billing)
        Definition: ...

    Project-level terms render first; feature-local terms follow
    grouped by owning feature. If both lists are empty, the
    output is the single line ``(no project vocabulary defined)``.
    """
    from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree

    if not project_vocab and not feature_vocab:
        return "(no project vocabulary defined)"

    def _render_one(node: Node, scope_label: str) -> str:
        content = (node.content or "").strip()
        definition = content
        disambiguation: str | None = None
        see_also_names: list[str] = []
        try:
            tree = extract_tag_tree(content, "vocab-entry")
            for child in tree.children:
                if child.tag == "definition":
                    definition = (child.text or "").strip() or definition
                elif child.tag == "disambiguation":
                    text = (child.text or "").strip()
                    if text:
                        disambiguation = text
                elif child.tag == "see-also":
                    for ref in child.children:
                        if ref.tag != "ref":
                            continue
                        ref_name = ref.attrs.get("name", "").strip()
                        ref_to = ref.attrs.get("to", "").strip()
                        label = ref_name or ref_to
                        if label:
                            see_also_names.append(label)
        except ParseError:
            pass

        parts: list[str] = [f"**{node.name}** ({scope_label})"]
        parts.append(f"Definition: {definition}")
        if disambiguation:
            parts.append(f"Disambiguation: {disambiguation}")
        if see_also_names:
            parts.append(f"See also: {', '.join(see_also_names)}")
        return "\n".join(parts)

    sections: list[str] = []

    if project_vocab:
        lines: list[str] = ["# Project vocabulary", ""]
        for node in project_vocab:
            lines.append(_render_one(node, "project-level"))
            lines.append("")
        sections.append("\n".join(lines).rstrip())

    if feature_vocab:
        from collections import defaultdict

        by_parent: dict[str, list[Node]] = defaultdict(list)
        for node in feature_vocab:
            if node.parent_id is None:
                continue
            by_parent[node.parent_id].append(node)

        lines = ["# Feature vocabulary", ""]
        names = feature_names or {}
        for parent_id in sorted(by_parent.keys()):
            parent_label = names.get(parent_id, parent_id)
            for node in sorted(by_parent[parent_id], key=lambda n: n.name):
                lines.append(_render_one(node, f"from feature: {parent_label}"))
                lines.append("")
        sections.append("\n".join(lines).rstrip())

    return "\n\n".join(sections)
