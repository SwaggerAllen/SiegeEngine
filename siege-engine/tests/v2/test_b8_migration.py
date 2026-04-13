"""Migration b8_project_settings smoke test.

Confirms that after the ``b8_project_settings`` revision runs, the
``projects`` table gains a nullable ``settings`` JSON column, that
existing rows can be inserted without supplying a value, and that
a JSON blob round-trips.
"""

from __future__ import annotations

import datetime
import json
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


def test_b8_adds_settings_column(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(projects)")
        cols = {row[1]: row for row in cur.fetchall()}
        assert "settings" in cols, "settings column missing after b8"
        # notnull=false — settings is an optional blob
        assert cols["settings"][3] == 0
    finally:
        conn.close()


def test_b8_project_row_without_settings_defaults_to_null(migrated_db: str) -> None:
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
        conn.commit()
        cur.execute("SELECT settings FROM projects WHERE id = 'p1'")
        row = cur.fetchone()
        assert row[0] is None
    finally:
        conn.close()


def test_b8_settings_json_round_trip(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        now = datetime.datetime.utcnow()
        payload = json.dumps({"generation_timeout_seconds": 1200})
        cur.execute(
            "INSERT INTO projects (id, name, description, git_repo_path, "
            "auto_push_enabled, settings, created_at, updated_at) "
            "VALUES ('p2', 'P', 'd', '/tmp', 0, ?, ?, ?)",
            (payload, now, now),
        )
        conn.commit()
        cur.execute("SELECT settings FROM projects WHERE id = 'p2'")
        (raw,) = cur.fetchone()
        assert json.loads(raw) == {"generation_timeout_seconds": 1200}
    finally:
        conn.close()
