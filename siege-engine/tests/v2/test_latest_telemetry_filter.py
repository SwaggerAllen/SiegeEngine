"""``_latest_telemetry`` must skip section="review" rows.

Both bootstrap generation and the AI self-review pass write to
the same ``GenerationTelemetry`` table. The review row lands
chronologically after the generation row (review runs post-
generation), so an unfiltered ``ORDER BY created_at DESC LIMIT 1``
surfaces review tokens on the "Last gen" telemetry line — which
misleads the user about the generation's actual cost.

These tests pin that both the bootstrap-routes and legacy
``backend.graph.routes`` copies of ``_latest_telemetry`` skip
review rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from backend.graph.bootstrap_routes import _latest_telemetry as bootstrap_latest
from backend.graph.routes import _latest_telemetry as routes_latest
from backend.models.telemetry import GenerationTelemetry


def _add_telemetry(db, project_id, node_id, *, section, prompt, completion, model, when):
    db.add(
        GenerationTelemetry(
            project_id=project_id,
            node_id=node_id,
            section=section,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            created_at=when,
        )
    )
    db.flush()


class TestBootstrapLatestTelemetryExcludesReview:
    def test_returns_generation_row_when_review_is_newer(self, db, project):
        node_id = f"expansion_{uuid.uuid4().hex[:8]}"
        base = datetime(2026, 4, 21, 12, 0, 0)
        # Generation wrote 5000 prompt tokens at T0.
        _add_telemetry(
            db,
            project.id,
            node_id,
            section="expansion",
            prompt=5000,
            completion=2500,
            model="claude-sonnet-4",
            when=base,
        )
        # Review wrote 800 prompt tokens at T+2s (newer).
        _add_telemetry(
            db,
            project.id,
            node_id,
            section="review",
            prompt=800,
            completion=200,
            model="claude-sonnet-4",
            when=base + timedelta(seconds=2),
        )

        telem = bootstrap_latest(db, project.id, node_id)
        assert telem is not None
        # Must be the generation row, not the review row.
        assert telem["prompt_tokens"] == 5000
        assert telem["completion_tokens"] == 2500

    def test_returns_none_when_only_review_rows_exist(self, db, project):
        node_id = f"expansion_{uuid.uuid4().hex[:8]}"
        _add_telemetry(
            db,
            project.id,
            node_id,
            section="review",
            prompt=800,
            completion=200,
            model="claude-sonnet-4",
            when=datetime(2026, 4, 21, 12, 0, 0),
        )
        # Defensive: if something ever enqueues a review without a
        # generation first, the "Last gen" display should show
        # nothing rather than review data.
        assert bootstrap_latest(db, project.id, node_id) is None


class TestRoutesLatestTelemetryExcludesReview:
    def test_returns_generation_row_when_review_is_newer(self, db, project):
        node_id = f"fanin_{uuid.uuid4().hex[:8]}"
        base = datetime(2026, 4, 21, 12, 0, 0)
        _add_telemetry(
            db,
            project.id,
            node_id,
            section="fanin",
            prompt=3000,
            completion=1500,
            model="claude-sonnet-4",
            when=base,
        )
        _add_telemetry(
            db,
            project.id,
            node_id,
            section="review",
            prompt=500,
            completion=100,
            model="claude-sonnet-4",
            when=base + timedelta(seconds=3),
        )
        telem = routes_latest(db, project.id, node_id)
        assert telem is not None
        assert telem.prompt_tokens == 3000
        assert telem.completion_tokens == 1500
