"""Shared test fixtures."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models import Project


def _id():
    return str(uuid.uuid4())


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def project(db):
    p = Project(
        id=_id(),
        name="Test Project",
        git_repo_path="/tmp/test-repo",
    )
    db.add(p)
    db.flush()
    return p
