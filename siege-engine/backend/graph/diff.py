"""Phase 12 before-vs-after diff computation for the review walker.

Two helpers, both keyed off a pinned ``GraphEvent.offset``:

* :func:`node_content_diff` — the ``Node.content`` field at
  ``pinned_offset`` versus now.
* :func:`fragment_diff` — every :class:`~backend.models.node.Fragment`
  the node owns, paired with its content at ``pinned_offset``.

Both go through :func:`backend.graph.review.get_or_build_snapshot`
to amortize the reducer-replay cost of reconstructing the pinned
state. The helpers return plain dicts/dataclasses rather than ORM
rows so the walker route can serialize them without worrying about
which session scope they came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.review import get_or_build_snapshot
from backend.models.node import Fragment, Node


@dataclass(frozen=True)
class ContentDiff:
    """``Node.content`` pair across the pinned-vs-live boundary.

    Both sides may be ``None`` in edge cases: the node didn't exist
    yet at ``pinned_offset`` (``before=None``) or was deleted since
    (``after=None``). The walker renders a "no content yet" hint
    on those branches rather than feeding a null string to the
    diff view.
    """

    before: str | None
    after: str | None


@dataclass(frozen=True)
class FragmentDiffEntry:
    """Before / after content for a single fragment owned by a node.

    ``fragment_kind`` is the fragment's kind (e.g. ``techspec``,
    ``pubapi``). The before / after nullability follows the same
    pattern as :class:`ContentDiff` — a fragment may not exist on
    one side of the diff (a sysarch rename may have created the
    ``pubapi`` fragment after the pin).
    """

    fragment_kind: str
    before: str | None
    after: str | None


def node_content_diff(
    session: Session,
    project_id: str,
    node_id: str,
    pinned_offset: int,
) -> ContentDiff:
    """Return the node's content at ``pinned_offset`` vs right now."""
    snapshot = get_or_build_snapshot(session, project_id, pinned_offset)
    before: str | None = None
    for entry in snapshot.get("nodes", []):
        if entry.get("id") == node_id:
            before = entry.get("content") or ""
            break
    live = session.get(Node, node_id)
    after: str | None = None
    if live is not None and live.project_id == project_id:
        after = live.content or ""
    return ContentDiff(before=before, after=after)


def fragment_diff(
    session: Session,
    project_id: str,
    node_id: str,
    pinned_offset: int,
) -> list[FragmentDiffEntry]:
    """Return per-fragment diffs for every fragment owned by ``node_id``.

    Unions the fragment kinds present at ``pinned_offset`` with the
    ones on the live row so the walker can show adds/deletes, not
    just content changes. Sorted by fragment_kind for a stable
    render order in the UI.
    """
    snapshot = get_or_build_snapshot(session, project_id, pinned_offset)
    before_by_kind: dict[str, str] = {}
    for frag in snapshot.get("fragments", []):
        if frag.get("owner_id") == node_id:
            before_by_kind[frag["fragment_kind"]] = frag.get("content") or ""

    live_rows = (
        session.execute(
            select(Fragment).where(
                Fragment.project_id == project_id,
                Fragment.owner_id == node_id,
            )
        )
        .scalars()
        .all()
    )
    after_by_kind: dict[str, str] = {f.fragment_kind: (f.content or "") for f in live_rows}

    kinds = sorted(set(before_by_kind.keys()) | set(after_by_kind.keys()))
    return [
        FragmentDiffEntry(
            fragment_kind=kind,
            before=before_by_kind.get(kind),
            after=after_by_kind.get(kind),
        )
        for kind in kinds
    ]


def node_diff_payload(
    session: Session,
    project_id: str,
    node_id: str,
    pinned_offset: int,
) -> dict[str, Any]:
    """Bundle node content + fragment diffs for one walker pane load.

    One-shot helper the walker route calls per node click. Keeps
    the HTTP response shape close to what the frontend walker
    renders: ``{node_content: {before, after}, fragments: [...],
    latest_change_summary: str | None}``.

    Phase 13 — the latest non-null ``Draft.change_summary`` for
    this target (any status) rides along so the walker detail
    pane can render the "why" above the diff without a second
    round-trip. Null when the node has no drafts or no draft
    ever carried a summary (fan-in targets, pre-Phase-13 nodes).
    """
    from sqlalchemy import select

    from backend.models.node import Draft

    content = node_content_diff(session, project_id, node_id, pinned_offset)
    frags = fragment_diff(session, project_id, node_id, pinned_offset)
    latest_summary = session.execute(
        select(Draft.change_summary)
        .where(
            Draft.project_id == project_id,
            Draft.target_id == node_id,
            Draft.change_summary.is_not(None),
        )
        .order_by(Draft.created_at.desc(), Draft.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "node_content": {
            "before": content.before,
            "after": content.after,
        },
        "fragments": [
            {
                "fragment_kind": f.fragment_kind,
                "before": f.before,
                "after": f.after,
            }
            for f in frags
        ],
        "latest_change_summary": latest_summary,
    }
