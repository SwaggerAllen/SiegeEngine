"""Project reference node helpers.

Reference entries are ``ref_*`` nodes — a first-class node tier
whose purpose is to carry supplemental documents (DSL specs,
deployment runbooks, cross-component invariants docs) that any
other node can pull into its regen context via an outgoing
``reference`` edge. See
``docs/architecture/v2-rearchitecture.md`` §Project references
for the full rationale.

Each ``ref_*`` node's ``content`` field holds a parseable
``<reference>`` XML block with two required children (``<title>``
and ``<body>``) and an optional ``<see-also>`` containing
``<ref to="ref_..."/>`` children. Grammar is enforced at authoring
time by ``validate_reference`` in ``backend.graph.parsers.validators``.

Unlike vocabulary (scoped via ``parent_id`` to project or feature),
refs are always top-level: the reducer
(``_enforce_reference_parent_constraint``) rejects any attempt to
parent a ref under another node. Any node can draw a ``reference``
edge to any ref (or to any other node — the edge type is
general-purpose advisory context), and the walker below pulls the
right chunk out of each target based on its tier.

Refs are **not** frozen after approval. Unlike bootstrap tiers,
``UpdateReference`` works regardless of current approval state
because refs don't mint children and therefore have no downstream
desync to guard against.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.fragments import FragmentKind, best_layered_fragment_content
from backend.models.node import Edge, Node

REF_TIER = "ref"
REFERENCE_EDGE_TYPE = "reference"


def list_project_references(session: Session, project_id: str) -> list[Node]:
    """Return every ``ref_*`` node in the project, ordered by name."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == REF_TIER,
            )
            .order_by(Node.name.asc())
        ).scalars()
    )


def reference_by_id(session: Session, ref_id: str) -> Node | None:
    """Return the ``ref_*`` node with ``id == ref_id``, or ``None``.

    Does not validate the ID's prefix — the caller is responsible for
    passing a ref id. The reducer's tier enforcement guarantees every
    row with ``tier == 'ref'`` carries a ``ref_*`` id.
    """
    node = session.get(Node, ref_id)
    if node is None or node.tier != REF_TIER:
        return None
    return node


def reference_by_name(session: Session, project_id: str, name: str) -> Node | None:
    """Look up a ref by its title/name within the project.

    Names must be unique within a project (enforced at creation time
    by the route handler), so this returns at most one node.
    """
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == REF_TIER,
            Node.name == name,
        )
    ).scalar_one_or_none()


def outgoing_reference_edges(session: Session, project_id: str, source_id: str) -> list[Edge]:
    """Return every ``reference`` edge whose source is ``source_id``."""
    return list(
        session.execute(
            select(Edge).where(
                Edge.project_id == project_id,
                Edge.edge_type == REFERENCE_EDGE_TYPE,
                Edge.source_id == source_id,
            )
        ).scalars()
    )


def incoming_reference_edges(session: Session, project_id: str, target_id: str) -> list[Edge]:
    """Return every ``reference`` edge whose target is ``target_id``.

    Used by the ref-detail UI to show "what pulls this ref into its
    regen context".
    """
    return list(
        session.execute(
            select(Edge).where(
                Edge.project_id == project_id,
                Edge.edge_type == REFERENCE_EDGE_TYPE,
                Edge.target_id == target_id,
            )
        ).scalars()
    )


def referenced_content_for_node(
    session: Session, project_id: str, source_id: str
) -> dict[str, str]:
    """Return a ``{target_id: rendered_content}`` map for ``source_id``.

    Walks the outgoing ``reference`` edges from ``source_id`` (the
    walker is source-tier-agnostic, so comparch / subcomparch / ref
    / any tier all share one code path). For each target node,
    dispatches on the target's tier to pull the appropriate chunk:

    * ``ref_*`` → the full ``Node.content`` XML rendered to prose
      (``<title>``, ``<body>``, ``<see-also>`` labels)
    * ``comp_*`` → the component's ``pubapi`` fragment content
    * ``policy_*`` → the policy's ``Node.content`` (prose rationale)
    * ``feat_*`` / ``resp_*`` / anything else → ``Node.content``

    Missing targets (dangling edge) and targets with empty content
    are skipped silently — validator-level dangling-edge catches live
    elsewhere.
    """
    edges = outgoing_reference_edges(session, project_id, source_id)
    result: dict[str, str] = {}
    for edge in edges:
        target = session.get(Node, edge.target_id)
        if target is None or target.project_id != project_id:
            continue
        rendered = _render_target_chunk(session, project_id, target)
        if rendered:
            result[edge.target_id] = rendered
    return result


def _render_target_chunk(session: Session, project_id: str, target: Node) -> str:
    """Pull the right content chunk out of ``target`` based on its tier."""
    if target.tier == REF_TIER:
        return _render_reference_content(target)
    if target.tier == "comp":
        # Layered read so a referenced top-level comp returns its
        # rich comparch pubapi (and a referenced subcomp returns
        # its subcomparch pubapi); falls through to the sysarch
        # skeletal seed when the higher layer is empty.
        rendered = best_layered_fragment_content(session, target, FragmentKind.PUBAPI)
        if rendered.strip():
            return rendered.strip()
        return (target.content or "").strip()
    # feat / resp / policy / vocab / everything else: fall back to
    # the node's own content.
    return (target.content or "").strip()


def _render_reference_content(node: Node) -> str:
    """Parse a ref's stored XML and return prompt-friendly prose.

    Mirrors the vocab renderer: best-effort parsing, falls back to
    the raw content string if the parse fails.
    """
    from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree

    content = (node.content or "").strip()
    if not content:
        return ""
    try:
        tree = extract_tag_tree(content, "reference")
    except ParseError:
        return content

    title = node.name
    body = ""
    see_also: list[str] = []
    for child in tree.children:
        if child.tag == "title":
            text = (child.text or "").strip()
            if text:
                title = text
        elif child.tag == "body":
            body = (child.text or "").strip()
        elif child.tag == "see-also":
            for ref in child.children:
                if ref.tag != "ref":
                    continue
                label = ref.attrs.get("to", "").strip()
                if label:
                    see_also.append(label)

    parts: list[str] = [f"**{title}**"]
    if body:
        parts.append(body)
    if see_also:
        parts.append(f"See also: {', '.join(see_also)}")
    return "\n\n".join(parts)


# ── Prompt-friendly rendering ────────────────────────────────


def render_referenced_content_summary(session: Session, project_id: str, source_id: str) -> str:
    """Build the "References" prompt section for a regen targeting ``source_id``.

    Pulls every target this node links to via outgoing ``reference``
    edges, renders them in a stable order (by target id), and formats
    them as prose. Returns the sentinel ``"(no external references)"``
    when there are no outgoing edges, so the prompt template always
    has something deterministic to render.
    """
    items = referenced_content_for_node(session, project_id, source_id)
    return format_referenced_content_summary(items)


def format_referenced_content_summary(items: dict[str, str]) -> str:
    """Render ``{target_id: rendered}`` into a prompt-friendly block.

    Output shape::

        # References

        ## target_id_1
        ...rendered content...

        ## target_id_2
        ...rendered content...

    Entries render in sorted target-id order so prompts are
    deterministic across regens. Returns
    ``"(no external references)"`` when ``items`` is empty.
    """
    if not items:
        return "(no external references)"

    lines: list[str] = ["# References", ""]
    for target_id in sorted(items.keys()):
        lines.append(f"## {target_id}")
        lines.append("")
        lines.append(items[target_id].strip())
        lines.append("")
    return "\n".join(lines).rstrip()
