"""Tests for project cloning."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.config import settings
from backend.git_manager.service import git_manager
from backend.models import Base, InputDocument, Project
from backend.projects.service import clone_project


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
def isolated_git_base(tmp_path, monkeypatch):
    """Point git_manager at a temp dir so tests don't touch the real repo store."""
    monkeypatch.setattr(settings, "git_repos_base_path", str(tmp_path))
    monkeypatch.setattr(git_manager, "base_path", tmp_path)
    return tmp_path


@pytest.fixture()
def source_project(db, isolated_git_base):
    """Create a source project with a git repo and a couple of input documents."""
    project = Project(id=_id(), name="Original", description="desc", git_repo_path="")
    db.add(project)
    db.flush()

    repo_path = git_manager.init_repo(project.id)
    project.git_repo_path = repo_path
    # Drop a file directly into the working tree so tests can verify the copy.
    # We avoid commit_artifact here because it requires a HEAD commit.
    from pathlib import Path as _Path

    (_Path(repo_path) / "README.md").write_text("hello")

    db.add(
        InputDocument(
            id=_id(),
            project_id=project.id,
            name="Project Document",
            content="project doc content",
            doc_type="project_doc",
        )
    )
    db.add(
        InputDocument(
            id=_id(),
            project_id=project.id,
            name="API Spec",
            content="spec content",
            doc_type="reference",
        )
    )
    db.commit()
    return project


class TestCloneProject:
    def test_creates_new_project(self, db, source_project):
        clone = clone_project(db, source_project.id)
        assert clone.id != source_project.id
        assert clone.name == "Original (copy)"
        assert clone.description == "desc"

    def test_custom_name(self, db, source_project):
        clone = clone_project(db, source_project.id, new_name="My Checkpoint")
        assert clone.name == "My Checkpoint"

    def test_copies_git_repo(self, db, source_project, isolated_git_base):
        clone = clone_project(db, source_project.id)
        cloned_repo = isolated_git_base / clone.id
        assert cloned_repo.exists()
        assert (cloned_repo / "README.md").read_text() == "hello"
        assert clone.git_repo_path == str(cloned_repo)

    def test_clones_input_documents(self, db, source_project):
        clone = clone_project(db, source_project.id)
        docs = (
            db.query(InputDocument)
            .filter_by(project_id=clone.id)
            .order_by(InputDocument.name)
            .all()
        )
        assert [d.name for d in docs] == ["API Spec", "Project Document"]
        assert {d.content for d in docs} == {"spec content", "project doc content"}

    def test_clones_input_docs_with_new_ids(self, db, source_project):
        clone = clone_project(db, source_project.id)
        src_ids = {
            d.id for d in db.query(InputDocument).filter_by(project_id=source_project.id).all()
        }
        clone_ids = {
            d.id for d in db.query(InputDocument).filter_by(project_id=clone.id).all()
        }
        assert src_ids.isdisjoint(clone_ids)

    def test_raises_for_missing_source(self, db, isolated_git_base):
        with pytest.raises(ValueError, match="not found"):
            clone_project(db, "nonexistent")

    def test_source_project_unchanged(self, db, source_project):
        src_doc_count_before = (
            db.query(InputDocument).filter_by(project_id=source_project.id).count()
        )
        clone_project(db, source_project.id)
        src_doc_count_after = (
            db.query(InputDocument).filter_by(project_id=source_project.id).count()
        )
        assert src_doc_count_before == src_doc_count_after
