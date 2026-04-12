"""Migration b3_vocab_extension smoke test.

Confirms that after the ``b3_vocab_extension`` revision runs:

* the ``nodes`` CHECK constraint allows the new tiers (``plan``,
  ``reqs``, ``sysarch``, ``manifest``, ``fanin``) in addition to the
  existing ones, and
* the ``fragments`` CHECK constraint allows the new ``techspec``
  fragment kind in addition to the existing ones.

Same pattern as ``test_b2_migration.py`` — throwaway SQLite file
driven by the real Alembic script directory.
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


def _insert_fragment(cur, frag_id: str, owner_id: str, kind: str, project_id: str = "p1") -> None:
    now = datetime.datetime.utcnow()
    cur.execute(
        "INSERT INTO fragments (id, project_id, owner_id, fragment_kind, content, updated_at) "
        "VALUES (?, ?, ?, ?, '', ?)",
        (frag_id, project_id, owner_id, kind, now),
    )


def test_b3_allows_new_node_tiers(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)

        # Previously allowed tiers still work.
        for i, tier in enumerate(("feat", "resp", "comp", "impl", "expansion")):
            _insert_node(cur, f"{tier[:4]}_OLDT000{i}", tier)

        # New tiers accepted.
        for i, tier in enumerate(("plan", "reqs", "sysarch", "manifest", "fanin")):
            _insert_node(cur, f"{tier[:4]}_NEWT000{i}", tier)

        conn.commit()
    finally:
        conn.close()


def test_b3_still_rejects_unknown_tier(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_node(cur, "garbage_BBBBBBBB", "nonsense")
    finally:
        conn.close()


def test_b3_allows_techspec_fragment_kind(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        # Owner node must exist first (FK constraint).
        _insert_node(cur, "comp_OWNER001", "comp")

        # All four fragment kinds accepted, including techspec.
        for kind in ("techspec", "pubapi", "privapi", "deps"):
            _insert_fragment(
                cur,
                f"comp_OWNER001_{kind}",
                "comp_OWNER001",
                kind,
            )

        conn.commit()
    finally:
        conn.close()


def test_b3_still_rejects_unknown_fragment_kind(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "comp_OWNER002", "comp")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_fragment(
                cur,
                "comp_OWNER002_bogus",
                "comp_OWNER002",
                "notakind",
            )
    finally:
        conn.close()
