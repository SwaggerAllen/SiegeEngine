"""Migration b2_expansion_tier smoke test.

Confirms that after the ``b2_expansion_tier`` revision runs, the
``nodes`` CHECK constraint allows ``tier='expansion'`` and still
rejects unknown tier values.

Uses a throwaway SQLite file driven by the real Alembic script
directory — the same path the app uses in ``database.init_db``.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import tempfile

import pytest
from alembic import command
from alembic.config import Config


@pytest.fixture()
def migrated_db(monkeypatch):
    """Apply the full Alembic migration chain onto a fresh SQLite file.

    Alembic's env.py reads ``settings.database_url`` — which was
    resolved at import time — so we have to monkeypatch that, not
    the environment variable, to redirect it to the temp file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    url = f"sqlite:///{tmp.name}"

    from backend.config import settings

    monkeypatch.setattr(settings, "database_url", url)

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield tmp.name
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def _insert_node(cur, node_id: str, tier: str, project_id: str = "p1") -> None:
    now = datetime.datetime.utcnow()
    cur.execute(
        "INSERT INTO nodes (id, project_id, tier, kind, name, "
        "display_order, content, created_at, updated_at) "
        "VALUES (?, ?, ?, 'domain', 'X', 0, '', ?, ?)",
        (node_id, project_id, tier, now, now),
    )


def test_b2_allows_expansion_tier(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        now = datetime.datetime.utcnow()
        cur.execute(
            "INSERT INTO projects (id, name, description, git_repo_path, "
            "auto_push_enabled, created_at, updated_at) "
            "VALUES ('p1', 'P', 'd', '/tmp', 0, ?, ?)",
            (now, now),
        )

        # All four foundation tiers still accepted.
        for i, tier in enumerate(("feat", "resp", "comp", "impl")):
            _insert_node(cur, f"{tier}_AAAA000{i}", tier)

        # New expansion tier accepted.
        _insert_node(cur, "expansion_AAAAAAAA", "expansion")

        conn.commit()
    finally:
        conn.close()


def test_b2_still_rejects_unknown_tier(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        now = datetime.datetime.utcnow()
        cur.execute(
            "INSERT INTO projects (id, name, description, git_repo_path, "
            "auto_push_enabled, created_at, updated_at) "
            "VALUES ('p1', 'P', 'd', '/tmp', 0, ?, ?)",
            (now, now),
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_node(cur, "garbage_BBBBBBBB", "nonsense")
    finally:
        conn.close()
