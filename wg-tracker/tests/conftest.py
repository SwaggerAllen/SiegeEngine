"""Pytest fixtures.

Tests run against a real PostgreSQL database (the generated tsvector column and
JSONB/enum features require it). Point WGTRACKER_TEST_DATABASE_URL at a throwaway
DB; it defaults to the local one provisioned for development.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "WGTRACKER_TEST_DATABASE_URL",
        "postgresql+psycopg://wg:wg@localhost:5432/wgtracker_test",
    ),
)
os.environ.setdefault("CONFIG_PATH", os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("PUBLIC_BASE_URL", "http://testserver")

from sqlalchemy import text  # noqa: E402

from wgtracker.config import reload_settings  # noqa: E402
from wgtracker.db import get_sessionmaker, reset_engine  # noqa: E402
from wgtracker.models import Base  # noqa: E402

reload_settings()
reset_engine()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    from wgtracker.db import get_engine

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all tables before each test for isolation."""
    from wgtracker.db import get_engine

    engine = get_engine()
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def session():
    s = get_sessionmaker()()
    try:
        yield s
        s.commit()
    finally:
        s.close()
