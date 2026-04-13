"""Migration b5_policies_tier smoke test.

Confirms that after the ``b5_policies_tier`` revision runs:

- the ``nodes`` CHECK constraint accepts tier ``policy``
- the ``fragments`` CHECK constraint accepts fragment kind ``policies``
- the ``edges`` CHECK constraint accepts edge type ``policy_application``
- all pre-existing tier / fragment / edge values still work

Same pattern as ``test_b3_migration.py`` — throwaway SQLite file
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


def _insert_edge(
    cur,
    edge_id: str,
    source_id: str,
    target_id: str,
    edge_type: str,
    project_id: str = "p1",
) -> None:
    now = datetime.datetime.utcnow()
    cur.execute(
        "INSERT INTO edges (id, project_id, edge_type, source_id, target_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (edge_id, project_id, edge_type, source_id, target_id, now),
    )


def test_b5_allows_policy_node_tier(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "policy_POLI0001", "policy")
        conn.commit()
    finally:
        conn.close()


def test_b5_preserves_existing_node_tiers(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        # Every tier from b3 still works.
        for i, tier in enumerate(
            (
                "feat",
                "resp",
                "comp",
                "impl",
                "plan",
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


def test_b5_allows_policies_fragment_kind(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "comp_OWNER001", "comp")
        for kind in ("techspec", "pubapi", "privapi", "policies", "deps"):
            _insert_fragment(
                cur,
                f"comp_OWNER001_{kind}",
                "comp_OWNER001",
                kind,
            )
        conn.commit()
    finally:
        conn.close()


def test_b5_still_rejects_unknown_fragment_kind(migrated_db: str) -> None:
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


def test_b5_allows_policy_application_edge(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "policy_APOL0001", "policy")
        _insert_node(cur, "comp_TARGET01", "comp")
        _insert_edge(
            cur,
            "edge_PAPP0001",
            "policy_APOL0001",
            "comp_TARGET01",
            "policy_application",
        )
        conn.commit()
    finally:
        conn.close()


def test_b5_preserves_existing_edge_types(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "comp_SRC00001", "comp")
        _insert_node(cur, "comp_DST00001", "comp")
        _insert_edge(cur, "edge_DEP00001", "comp_SRC00001", "comp_DST00001", "dependency")
        _insert_edge(cur, "edge_DMP00001", "comp_SRC00001", "comp_DST00001", "domain_parent")
        conn.commit()
    finally:
        conn.close()


def test_b5_still_rejects_unknown_edge_type(migrated_db: str) -> None:
    conn = sqlite3.connect(migrated_db)
    try:
        cur = conn.cursor()
        _insert_project(cur)
        _insert_node(cur, "comp_SRC00002", "comp")
        _insert_node(cur, "comp_DST00002", "comp")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_edge(
                cur,
                "edge_BAD00001",
                "comp_SRC00002",
                "comp_DST00002",
                "notakind",
            )
    finally:
        conn.close()
