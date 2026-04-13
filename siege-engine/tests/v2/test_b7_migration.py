"""Migration b7_feature_metadata smoke test.

Confirms that after the ``b7_feature_metadata`` revision runs, the
``nodes`` table gains ``group_label`` (nullable string) and
``is_implicit`` (non-null bool defaulting to false) columns, and
that existing and new rows can use them.

Same pattern as ``test_b3_migration.py`` / ``test_b5_migration.py``.
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


def _insert_project(cur, project_id: str = "p1") -> None:
    now = datetime.datetime.utcnow()
    cur.execute(
        "INSERT INTO projects (id, name, description, git_repo_path, "
        "auto_push_enabled, created_at, updated_at) "
        "VALUES (?, 'P', 'd', '/tmp', 0, ?, ?)",
        (project_id, now, now),
    )


def test_b7_adds_group_label_and_is_implicit_columns(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        # pragma table_info returns (cid, name, type, notnull, dflt_value, pk)
        cur.execute("PRAGMA table_info(nodes)")
        cols = {row[1]: row for row in cur.fetchall()}
        assert "group_label" in cols, "group_label column missing after b7"
        assert "is_implicit" in cols, "is_implicit column missing after b7"
        # group_label is nullable
        assert cols["group_label"][3] == 0  # notnull=false
        # is_implicit is non-null
        assert cols["is_implicit"][3] == 1  # notnull=true
    finally:
        conn.close()


def test_b7_feature_row_with_group_and_implicit(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        now = datetime.datetime.utcnow()
        cur.execute(
            "INSERT INTO nodes (id, project_id, tier, kind, name, "
            "display_order, content, group_label, is_implicit, "
            "created_at, updated_at) "
            "VALUES (?, ?, 'feat', 'domain', ?, 0, '', ?, 1, ?, ?)",
            ("feat_ABCD0001", "p1", "Password Reset", "User Management", now, now),
        )
        conn.commit()

        cur.execute(
            "SELECT group_label, is_implicit FROM nodes WHERE id = ?",
            ("feat_ABCD0001",),
        )
        row = cur.fetchone()
        assert row[0] == "User Management"
        # sqlite stores bool as int 0/1
        assert row[1] == 1
    finally:
        conn.close()


def test_b7_non_feature_row_defaults_to_null_and_false(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        now = datetime.datetime.utcnow()
        # Insert a comp node without specifying the new columns —
        # they should default to null and false.
        cur.execute(
            "INSERT INTO nodes (id, project_id, tier, kind, name, "
            "display_order, content, created_at, updated_at) "
            "VALUES (?, ?, 'comp', 'domain', ?, 0, '', ?, ?)",
            ("comp_ABCD0001", "p1", "Some Component", now, now),
        )
        conn.commit()

        cur.execute(
            "SELECT group_label, is_implicit FROM nodes WHERE id = ?",
            ("comp_ABCD0001",),
        )
        row = cur.fetchone()
        assert row[0] is None
        assert row[1] == 0
    finally:
        conn.close()


def test_b7_chain_preserves_existing_tiers(migrated_db: str) -> None:
    """Full migration chain through b7 still accepts all tiers from b6."""
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        now = datetime.datetime.utcnow()
        for i, tier in enumerate(
            (
                "feat",
                "resp",
                "comp",
                "impl",
                "plan",
                "policy",
                "expansion",
                "reqs",
                "subreqs",
                "sysarch",
                "manifest",
                "fanin",
            )
        ):
            cur.execute(
                "INSERT INTO nodes (id, project_id, tier, kind, name, "
                "display_order, content, created_at, updated_at) "
                "VALUES (?, ?, ?, 'domain', 'X', 0, '', ?, ?)",
                (f"{tier[:4]}_CHAIN00{i}", "p1", tier, now, now),
            )
        conn.commit()
    finally:
        conn.close()
