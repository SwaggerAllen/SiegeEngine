"""Per-tier review-summary aggregation.

Drives the workshop-prompt-quality dashboard: walk every node in a
tier, parse its currently-approved draft's ``review_text`` (or the
node's own ``review_text`` for fanin), aggregate the per-review
intros + scores into a panel-ready summary.

The endpoint reads the same ``BootstrapTierConfig`` registry that
``tier_ops_routes`` uses for reset / review-sweep, so adding a new
tier to the dashboard is the same one-line registry edit.

Read-only by design — never mutates anything, never enqueues jobs.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.parsers.review_xml import ReviewXMLError, parse_review
from backend.models.node import Draft, Node


@dataclass(frozen=True)
class ReviewEntry:
    """One parseable review's display fields, keyed by tier scope."""

    scope_id: str
    scope_label: str
    score: int
    intro: str
    handles_count: int
    arch_count: int
    approved_at: str | None


@dataclass(frozen=True)
class ReviewMissing:
    """One tier scope whose review couldn't be summarised.

    ``reason`` is one of:
    - ``"no draft"`` — node exists but no pending or approved draft
    - ``"empty review"`` — draft exists but its review didn't run yet
      (or is still in flight)
    - ``"parse failed: …"`` — review_text is present but malformed
    """

    scope_id: str
    scope_label: str
    reason: str


@dataclass(frozen=True)
class ScoreStats:
    min: int
    max: int
    mean: float
    median: float


@dataclass(frozen=True)
class ScoreBuckets:
    band_0_50: int
    band_51_70: int
    band_71_80: int
    band_81_90: int
    band_91_100: int


@dataclass(frozen=True)
class ReviewSummary:
    """Aggregate + per-scope detail for a single tier in a project."""

    tier: str
    tier_name: str
    draft_count: int
    reviewed_count: int
    missing_count: int
    score_stats: ScoreStats | None
    score_buckets: ScoreBuckets
    handles_count_mean: float | None
    arch_count_mean: float | None
    reviews: tuple[ReviewEntry, ...]
    missing: tuple[ReviewMissing, ...]


def gather_tier_review_summary(
    db: Session,
    project_id: str,
    tier: str,
    *,
    batch_id: str | None = None,
) -> ReviewSummary:
    """Aggregate review-summary stats for every scope in a tier.

    Iterates the same scope set that ``tier_ops_routes`` uses, so a
    "missing" scope here matches a "skipped" scope on the bulk
    review-sweep. Reviews are returned worst-score-first to match
    the workshop loop's iteration order.

    When ``batch_id`` is provided, the per-scope draft lookup is
    constrained to drafts whose ``Draft.batch_id`` matches — so the
    summary only includes reviews of drafts produced as part of
    that operation. A scope whose draft isn't in the batch is
    reported as ``missing`` with a "not in batch" reason. Used to
    scope the review summary to the most recent canonical-cohort
    generation cycle.

    Raises ``KeyError`` when ``tier`` isn't in the registry — caller
    is expected to translate that into a 404.
    """
    from backend.graph.tier_ops_routes import _registry

    reg = _registry()
    if tier not in reg:
        raise KeyError(tier)
    config, iter_scope_ids = reg[tier]
    scopes = iter_scope_ids(db, project_id)

    reviews: list[ReviewEntry] = []
    missing: list[ReviewMissing] = []
    for scope_ids in scopes:
        node = config.get_node(db, project_id, *scope_ids)
        if node is None:
            continue
        scope_id = scope_ids[-1] if scope_ids else node.id
        scope_label = node.name or scope_id

        # Reviews live on drafts of any non-discarded status. Prefer
        # the most recent draft overall — pending drafts win over
        # older approved ones, since pending is what the user is
        # actively iterating on. Discarded drafts are noise; their
        # review_text references prior content that's been
        # superseded.
        draft_query = (
            select(Draft)
            .where(
                Draft.project_id == project_id,
                Draft.target_id == node.id,
                Draft.status.in_(("pending", "approved")),
            )
            .order_by(Draft.created_at.desc())
        )
        if batch_id is not None:
            draft_query = draft_query.where(Draft.batch_id == batch_id)
        target_draft = db.execute(draft_query).scalars().first()
        if target_draft is None:
            reason = "no draft in batch" if batch_id is not None else "no draft"
            missing.append(ReviewMissing(scope_id=scope_id, scope_label=scope_label, reason=reason))
            continue
        if not (target_draft.review_text or "").strip():
            missing.append(
                ReviewMissing(scope_id=scope_id, scope_label=scope_label, reason="empty review")
            )
            continue
        try:
            parsed = parse_review(target_draft.review_text)
        except ReviewXMLError as exc:
            missing.append(
                ReviewMissing(
                    scope_id=scope_id,
                    scope_label=scope_label,
                    reason=f"parse failed: {exc}",
                )
            )
            continue
        approved_at = target_draft.created_at.isoformat() if target_draft.created_at else None
        reviews.append(
            ReviewEntry(
                scope_id=scope_id,
                scope_label=scope_label,
                score=parsed.score,
                intro=parsed.intro,
                handles_count=len(parsed.handles_structure),
                arch_count=len(parsed.architectural_decisions),
                approved_at=approved_at,
            )
        )

    reviews.sort(key=lambda r: (r.score, r.scope_label))
    return _build_summary(tier=tier, tier_name=config.tier_name, reviews=reviews, missing=missing)


def _build_summary(
    *,
    tier: str,
    tier_name: str,
    reviews: list[ReviewEntry],
    missing: list[ReviewMissing],
) -> ReviewSummary:
    if reviews:
        scores = [r.score for r in reviews]
        score_stats: ScoreStats | None = ScoreStats(
            min=min(scores),
            max=max(scores),
            mean=statistics.fmean(scores),
            median=statistics.median(scores),
        )
        handles_mean: float | None = statistics.fmean(r.handles_count for r in reviews)
        arch_mean: float | None = statistics.fmean(r.arch_count for r in reviews)
    else:
        score_stats = None
        handles_mean = None
        arch_mean = None

    buckets = ScoreBuckets(
        band_0_50=sum(1 for r in reviews if 0 <= r.score <= 50),
        band_51_70=sum(1 for r in reviews if 51 <= r.score <= 70),
        band_71_80=sum(1 for r in reviews if 71 <= r.score <= 80),
        band_81_90=sum(1 for r in reviews if 81 <= r.score <= 90),
        band_91_100=sum(1 for r in reviews if 91 <= r.score <= 100),
    )
    return ReviewSummary(
        tier=tier,
        tier_name=tier_name,
        draft_count=len(reviews) + len(missing),
        reviewed_count=len(reviews),
        missing_count=len(missing),
        score_stats=score_stats,
        score_buckets=buckets,
        handles_count_mean=handles_mean,
        arch_count_mean=arch_mean,
        reviews=tuple(reviews),
        missing=tuple(missing),
    )


def _draft_count_for_tier(db: Session, project_id: str, tier: str) -> int:
    """Return the number of distinct nodes in ``tier`` with at least
    one approved draft. Used by the test suite to sanity-check the
    aggregation against ``Draft`` rows directly without re-running
    the full registry walk.
    """
    return (
        db.execute(
            select(Draft.target_id)
            .join(Node, Node.id == Draft.target_id)
            .where(
                Draft.project_id == project_id,
                Draft.status == "approved",
                Node.tier == tier,
            )
            .distinct()
        )
        .scalars()
        .all()
        .__len__()
    )
