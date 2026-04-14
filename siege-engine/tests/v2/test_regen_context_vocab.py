"""Tests for stage 4 of Phase 5.5: vocab context in regen prompts.

Covers:

- ``vocabulary.render_vocab_summary_all`` returns project + all
  feature vocab as prompt-friendly prose.
- ``vocabulary.render_vocab_summary_for_node`` filters feature
  vocab by reachability from the target node.
- ``format_regen_context`` and ``format_regen_context_for_sub``
  populate ``vocab_summary`` via the shared formatter.
- The XML-to-prose formatter correctly renders
  definition / disambiguation / see-also sections.
- The "(no project vocabulary defined)" empty fallback works.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph import vocabulary
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import Project


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(p)
    db.commit()
    return p


def _seed_feat(db: Session, project_id: str, name: str) -> str:
    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=0,
            content=f"{name} intent.",
        ),
    )
    return feat_id


def _seed_vocab(
    db: Session,
    project_id: str,
    name: str,
    *,
    parent_id: str | None = None,
    definition: str = "Default definition.",
    disambiguation: str | None = None,
    see_also: list[str] | None = None,
) -> str:
    vocab_id = mint(db, Kind.VOCAB)
    entry_parts = [f"<definition>{definition}</definition>"]
    if disambiguation:
        entry_parts.append(f"<disambiguation>{disambiguation}</disambiguation>")
    if see_also:
        refs = "".join(f'<ref name="{r}"/>' for r in see_also)
        entry_parts.append(f"<see-also>{refs}</see-also>")
    content = f"<vocab-entry>{''.join(entry_parts)}</vocab-entry>"
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=vocab_id,
            tier="vocab",
            kind="domain",
            parent_id=parent_id,
            name=name,
            display_order=0,
            content=content,
        ),
    )
    return vocab_id


class TestRenderVocabSummaryAll:
    def test_empty_returns_fallback(self, db, project):
        summary = vocabulary.render_vocab_summary_all(db, project.id)
        assert summary == "(no project vocabulary defined)"

    def test_project_level_only(self, db, project):
        _seed_vocab(db, project.id, "boulder", definition="A unit of structured work.")
        _seed_vocab(db, project.id, "foundation", definition="The catch-all component.")
        db.commit()

        summary = vocabulary.render_vocab_summary_all(db, project.id)
        assert "# Project vocabulary" in summary
        assert "**boulder**" in summary
        assert "**foundation**" in summary
        assert "A unit of structured work." in summary
        assert "The catch-all component." in summary
        assert "# Feature vocabulary" not in summary

    def test_includes_feature_vocab(self, db, project):
        feat_billing = _seed_feat(db, project.id, "Billing")
        _seed_vocab(db, project.id, "boulder", definition="Project def.")
        _seed_vocab(
            db,
            project.id,
            "tranche",
            parent_id=feat_billing,
            definition="A billing batch.",
        )
        db.commit()

        summary = vocabulary.render_vocab_summary_all(db, project.id)
        assert "# Project vocabulary" in summary
        assert "# Feature vocabulary" in summary
        assert "**boulder**" in summary
        assert "**tranche**" in summary
        assert "from feature: Billing" in summary

    def test_disambiguation_rendered(self, db, project):
        _seed_vocab(
            db,
            project.id,
            "boulder",
            definition="Def.",
            disambiguation="Not a leaf node.",
        )
        db.commit()
        summary = vocabulary.render_vocab_summary_all(db, project.id)
        assert "Definition: Def." in summary
        assert "Disambiguation: Not a leaf node." in summary

    def test_see_also_rendered(self, db, project):
        _seed_vocab(
            db,
            project.id,
            "boulder",
            definition="Def.",
            see_also=["leaf", "fan-out"],
        )
        db.commit()
        summary = vocabulary.render_vocab_summary_all(db, project.id)
        assert "See also: leaf, fan-out" in summary


class TestRenderVocabSummaryForNode:
    def test_feat_target_returns_own_feature_vocab(self, db, project):
        feat_billing = _seed_feat(db, project.id, "Billing")
        feat_auth = _seed_feat(db, project.id, "Auth")
        _seed_vocab(db, project.id, "boulder", definition="Project.")
        _seed_vocab(db, project.id, "tranche", parent_id=feat_billing, definition="Billing.")
        _seed_vocab(db, project.id, "session", parent_id=feat_auth, definition="Auth.")
        db.commit()

        summary = vocabulary.render_vocab_summary_for_node(db, project.id, feat_billing)
        assert "**boulder**" in summary  # project-level always included
        assert "**tranche**" in summary  # Billing's own vocab
        assert "**session**" not in summary  # Auth's vocab excluded

    def test_missing_target_returns_project_level_only(self, db, project):
        _seed_vocab(db, project.id, "boulder", definition="Project term.")
        db.commit()
        summary = vocabulary.render_vocab_summary_for_node(db, project.id, "feat_MISSING0")
        assert "**boulder**" in summary
        # No feature section because the target wasn't found.
        assert "# Feature vocabulary" not in summary
