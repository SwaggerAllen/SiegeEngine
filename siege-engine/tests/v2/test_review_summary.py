"""Tests for the per-tier review-summary aggregation.

Two layers of coverage:

- ``gather_tier_review_summary`` (pure-ish service helper) — exercises
  the parsing + aggregation math without touching FastAPI. Each
  scenario seeds drafts with hand-crafted ``<review>`` XML and checks
  the returned ``ReviewSummary`` shape.
- ``GET /tiers/{tier}/review-summary`` endpoint — one happy-path test
  + a 404 for unknown tier. The service's behaviour is exercised at
  unit level so the route test only verifies wiring.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.fragments import FragmentKind, fragment_id  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.review_summary import gather_tier_review_summary  # noqa: E402
from backend.graph.sysarch import bootstrap_sysarch_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.node import Draft  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


def _review_xml(*, intro: str, score: int, h_findings: int, a_findings: int) -> str:
    """Build a parseable ``<review>`` XML blob."""
    handles = "".join(
        f'<finding id="h{i}">handles finding {i}</finding>' for i in range(1, h_findings + 1)
    )
    arch = "".join(
        f'<finding id="a{i}">arch finding {i}</finding>' for i in range(1, a_findings + 1)
    )
    return (
        "<review>"
        f"<intro>{intro}</intro>"
        f"<score>{score}</score>"
        f"<handles-structure>{handles}</handles-structure>"
        f"<architectural-decisions>{arch}</architectural-decisions>"
        "</review>"
    )


def _seed_project(db: Session) -> str:
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return project_id


def _seed_comp_with_review(
    db: Session,
    project_id: str,
    *,
    name: str,
    order: int,
    review_text: str | None,
    parent_resp_id: str | None = None,
) -> str:
    """Seed a top-level comp + an approved draft carrying ``review_text``.

    Pass ``review_text=None`` to skip the draft entirely (simulates
    "no approved draft" missing case). Pass an empty string to seed
    an approved draft with empty review_text ("empty review" case).
    """
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"<comparch>{name}</comparch>",
        ),
    )
    for kind, content in (
        (FragmentKind.TECHSPEC, f"{name} role"),
        (FragmentKind.PUBAPI, f"{name} api"),
    ):
        append_event(
            db,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(comp_id, kind),
                owner_id=comp_id,
                fragment_kind=kind,
                new_content=content,
            ),
        )
    if parent_resp_id is not None:
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=parent_resp_id,
                target_id=comp_id,
            ),
        )
    if review_text is not None:
        draft = Draft(
            id=f"draft_{name}_{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            target_type="node",
            target_id=comp_id,
            content=f"<comparch>{name}</comparch>",
            status="approved",
            batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            review_text=review_text,
            created_at=datetime(2026, 4, 1, 12, 0, order),
        )
        db.add(draft)
    return comp_id


# ── Service-helper unit tests ──────────────────────────────────────


class TestGatherTierReviewSummary:
    def test_empty_project_yields_empty_summary(self, db):
        project_id = _seed_project(db)
        db.commit()
        summary = gather_tier_review_summary(db, project_id, "comparch")
        assert summary.tier == "comparch"
        assert summary.draft_count == 0
        assert summary.reviewed_count == 0
        assert summary.missing_count == 0
        assert summary.score_stats is None
        assert summary.score_buckets.band_0_30 == 0
        assert summary.score_buckets.band_31_60 == 0
        assert summary.score_buckets.band_61_85 == 0
        assert summary.score_buckets.band_86_100 == 0
        assert summary.handles_count_mean is None
        assert summary.arch_count_mean is None
        assert summary.reviews == ()
        assert summary.missing == ()

    def test_aggregates_scores_across_per_comp_tier(self, db):
        project_id = _seed_project(db)
        _seed_comp_with_review(
            db,
            project_id,
            name="Billing",
            order=0,
            review_text=_review_xml(intro="Billing intro", score=72, h_findings=2, a_findings=1),
        )
        _seed_comp_with_review(
            db,
            project_id,
            name="Auth",
            order=1,
            review_text=_review_xml(intro="Auth intro", score=45, h_findings=4, a_findings=2),
        )
        _seed_comp_with_review(
            db,
            project_id,
            name="Foundation",
            order=2,
            review_text=_review_xml(intro="Foundation intro", score=92, h_findings=0, a_findings=0),
        )
        db.commit()

        summary = gather_tier_review_summary(db, project_id, "comparch")
        assert summary.draft_count == 3
        assert summary.reviewed_count == 3
        assert summary.missing_count == 0

        assert summary.score_stats is not None
        assert summary.score_stats.min == 45
        assert summary.score_stats.max == 92
        assert summary.score_stats.median == 72
        # mean = (72 + 45 + 92) / 3 ≈ 69.66...
        assert round(summary.score_stats.mean, 2) == 69.67

        # Buckets: 45 → 31-60, 72 → 61-85, 92 → 86-100. None in 0-30.
        assert summary.score_buckets.band_0_30 == 0
        assert summary.score_buckets.band_31_60 == 1
        assert summary.score_buckets.band_61_85 == 1
        assert summary.score_buckets.band_86_100 == 1

        # Handles + arch count means: (2+4+0)/3 = 2.0; (1+2+0)/3 ≈ 1.0
        assert summary.handles_count_mean is not None
        assert round(summary.handles_count_mean, 2) == 2.0
        assert summary.arch_count_mean is not None
        assert round(summary.arch_count_mean, 2) == 1.0

    def test_reviews_sorted_worst_first(self, db):
        project_id = _seed_project(db)
        _seed_comp_with_review(
            db,
            project_id,
            name="Billing",
            order=0,
            review_text=_review_xml(intro="b", score=72, h_findings=0, a_findings=0),
        )
        _seed_comp_with_review(
            db,
            project_id,
            name="Auth",
            order=1,
            review_text=_review_xml(intro="a", score=45, h_findings=0, a_findings=0),
        )
        _seed_comp_with_review(
            db,
            project_id,
            name="Foundation",
            order=2,
            review_text=_review_xml(intro="f", score=92, h_findings=0, a_findings=0),
        )
        db.commit()
        summary = gather_tier_review_summary(db, project_id, "comparch")
        assert [r.scope_label for r in summary.reviews] == ["Auth", "Billing", "Foundation"]
        assert [r.score for r in summary.reviews] == [45, 72, 92]

    def test_missing_categorises_no_draft_empty_review_and_parse_failure(self, db):
        project_id = _seed_project(db)
        # No draft at all → "no approved draft"
        _seed_comp_with_review(
            db,
            project_id,
            name="NoDraft",
            order=0,
            review_text=None,
        )
        # Approved draft but empty review_text → "empty review"
        _seed_comp_with_review(
            db,
            project_id,
            name="EmptyReview",
            order=1,
            review_text="",
        )
        # Approved draft with malformed review_text → "parse failed: …"
        _seed_comp_with_review(
            db,
            project_id,
            name="BadXml",
            order=2,
            review_text="<review>broken",
        )
        # One healthy review so the summary has a baseline.
        _seed_comp_with_review(
            db,
            project_id,
            name="Ok",
            order=3,
            review_text=_review_xml(intro="ok", score=80, h_findings=1, a_findings=1),
        )
        db.commit()

        summary = gather_tier_review_summary(db, project_id, "comparch")
        assert summary.draft_count == 4
        assert summary.reviewed_count == 1
        assert summary.missing_count == 3
        reasons_by_label = {m.scope_label: m.reason for m in summary.missing}
        assert reasons_by_label["NoDraft"] == "no approved draft"
        assert reasons_by_label["EmptyReview"] == "empty review"
        assert reasons_by_label["BadXml"].startswith("parse failed:")

    def test_singleton_tier_sysarch(self, db):
        project_id = _seed_project(db)
        sysarch_id = bootstrap_sysarch_node(db, project_id)
        # Approved sysarch content + a draft with review_text.
        append_event(
            db,
            project_id,
            ev.NodeContentUpdated(node_id=sysarch_id, new_content="<sysarch>ok</sysarch>"),
        )
        draft = Draft(
            id=f"draft_sysarch_{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            target_type="node",
            target_id=sysarch_id,
            content="<sysarch>ok</sysarch>",
            status="approved",
            batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            review_text=_review_xml(intro="sysarch verdict", score=66, h_findings=2, a_findings=1),
            created_at=datetime(2026, 4, 1, 12, 0, 0),
        )
        db.add(draft)
        db.commit()

        summary = gather_tier_review_summary(db, project_id, "sysarch")
        assert summary.tier == "sysarch"
        assert summary.reviewed_count == 1
        assert summary.missing_count == 0
        assert summary.reviews[0].score == 66
        assert summary.reviews[0].intro == "sysarch verdict"

    def test_unknown_tier_raises_keyerror(self, db):
        project_id = _seed_project(db)
        db.commit()
        with pytest.raises(KeyError):
            gather_tier_review_summary(db, project_id, "manifest")


# ── Endpoint smoke tests ───────────────────────────────────────────


@pytest.fixture()
def client(db):
    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestReviewSummaryEndpoint:
    def test_happy_path_returns_full_payload(self, client, db):
        project_id = _seed_project(db)
        _seed_comp_with_review(
            db,
            project_id,
            name="Billing",
            order=0,
            review_text=_review_xml(intro="Billing intro", score=72, h_findings=2, a_findings=1),
        )
        _seed_comp_with_review(
            db,
            project_id,
            name="Auth",
            order=1,
            review_text=_review_xml(intro="Auth intro", score=45, h_findings=4, a_findings=2),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project_id}/tiers/comparch/review-summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "comparch"
        assert body["draft_count"] == 2
        assert body["reviewed_count"] == 2
        assert body["missing_count"] == 0
        assert body["score_stats"]["min"] == 45
        assert body["score_stats"]["max"] == 72
        assert body["score_buckets"]["band_31_60"] == 1
        assert body["score_buckets"]["band_61_85"] == 1
        assert [r["scope_label"] for r in body["reviews"]] == ["Auth", "Billing"]
        assert body["reviews"][0]["intro"] == "Auth intro"
        assert body["reviews"][0]["handles_count"] == 4
        assert body["reviews"][0]["arch_count"] == 2

    def test_unknown_tier_returns_422(self, client, db):
        project_id = _seed_project(db)
        db.commit()
        # FastAPI rejects path params that don't match the Literal
        # union before reaching our handler; that's a 422 (validation
        # error), not a 404. Either way the failure mode is "the
        # endpoint refuses to dispatch on an unknown tier."
        resp = client.get(f"/api/projects/{project_id}/tiers/bogus/review-summary")
        assert resp.status_code == 422

    def test_unknown_project_returns_404(self, client, db):
        resp = client.get("/api/projects/nonexistent_proj/tiers/comparch/review-summary")
        assert resp.status_code == 404
