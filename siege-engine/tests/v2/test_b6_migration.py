"""Migration b6_subreqs_tier smoke test.

Confirms that after the ``b6_subreqs_tier`` revision runs, the
``nodes`` CHECK constraint accepts tier ``subreqs`` in addition
to all pre-existing tiers from b5.

Same pattern as ``test_b3_migration.py`` and ``test_b5_migration.py``
— throwaway SQLite file driven by the real Alembic script directory.
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


def _insert_node(cur, node_id: str, tier: str, project_id: str = "p1") -> None:
    now = datetime.datetime.utcnow()
    cur.execute(
        "INSERT INTO nodes (id, project_id, tier, kind, name, "
        "display_order, content, created_at, updated_at) "
        "VALUES (?, ?, ?, 'domain', 'X', 0, '', ?, ?)",
        (node_id, project_id, tier, now, now),
    )


def test_b6_allows_subreqs_node_tier(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "subr_SUBR0001", "subreqs")
        conn.commit()
    finally:
        conn.close()


def test_b6_preserves_existing_node_tiers(migrated_db: str) -> None:
    """Every tier from b5 still works — no regression on the chain."""
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
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
                "sysarch",
                "manifest",
                "fanin",
            )
        ):
            _insert_node(cur, f"{tier[:4]}_OLDT000{i}", tier)
        conn.commit()
    finally:
        conn.close()


def test_b6_still_rejects_unknown_node_tier(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_node(cur, "garb_BBBBBBBB", "nonsense")
    finally:
        conn.close()
