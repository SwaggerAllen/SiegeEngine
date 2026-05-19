"""Tests for the project-creation GitHub wire-up.

Two contracts under test:

1. ``derive_github_slug`` — turns the four common GitHub clone URL
   shapes into the ``owner/repo`` slug; returns None for anything else
   so the caller can supply an explicit slug.
2. ``create_project`` — when ``remote_url`` is provided, stores it on
   the Project row AND calls into ``git_manager.add_remote`` so the
   local clone has ``origin`` set immediately. Failure of the remote
   add is non-fatal — the project still gets created.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("SIEGE_ANTHROPIC_API_KEY", "test")
os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")
os.environ.setdefault("SIEGE_DISABLE_AI_REVIEW", "1")

import pytest  # noqa: E402

from backend.projects.service import create_project, derive_github_slug  # noqa: E402


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/SwaggerAllen/haven", "SwaggerAllen/haven"),
        ("https://github.com/SwaggerAllen/haven.git", "SwaggerAllen/haven"),
        ("https://github.com/SwaggerAllen/haven/", "SwaggerAllen/haven"),
        ("git@github.com:SwaggerAllen/haven.git", "SwaggerAllen/haven"),
        ("ssh://git@github.com/SwaggerAllen/haven.git", "SwaggerAllen/haven"),
        ("https://github.com/foo/repo-with-dashes.git", "foo/repo-with-dashes"),
        ("https://github.com/foo/repo.with.dots.git", "foo/repo.with.dots"),
        ("https://gitlab.com/foo/bar.git", None),
        ("not-a-url", None),
        ("", None),
        (None, None),
    ],
)
def test_derive_github_slug(url, expected):
    assert derive_github_slug(url) == expected


def test_create_project_with_remote_calls_add_remote(db, tmp_path, monkeypatch):
    """When remote_url is provided, create_project should store it on
    the Project row and call git_manager.add_remote with the project's
    id + URL. The slug should auto-derive from the URL."""
    fake_path = str(tmp_path / "repo")
    monkeypatch.setattr(
        "backend.projects.service.git_manager.init_repo",
        MagicMock(return_value=fake_path),
    )
    monkeypatch.setattr(
        "backend.projects.service.git_manager.commit_artifact",
        MagicMock(return_value="abc123"),
    )
    add_remote = MagicMock()
    monkeypatch.setattr("backend.projects.service.git_manager.add_remote", add_remote)
    monkeypatch.setattr(
        "backend.projects.service.bootstrap_expansion_node",
        MagicMock(),
    )
    monkeypatch.setattr(
        "backend.projects.service.pipeline_queue.enqueue",
        MagicMock(),
    )

    project = create_project(
        db,
        name="haven",
        description=None,
        project_doc_content="# haven\n",
        remote_url="https://github.com/SwaggerAllen/haven.git",
    )

    assert project.remote_url == "https://github.com/SwaggerAllen/haven.git"
    assert project.github_repo_slug == "SwaggerAllen/haven"
    add_remote.assert_called_once_with(project.id, "https://github.com/SwaggerAllen/haven.git")


def test_create_project_without_remote_leaves_fields_null(db, tmp_path, monkeypatch):
    """No remote_url ⇒ no add_remote call, slug stays null."""
    fake_path = str(tmp_path / "repo")
    monkeypatch.setattr(
        "backend.projects.service.git_manager.init_repo",
        MagicMock(return_value=fake_path),
    )
    monkeypatch.setattr(
        "backend.projects.service.git_manager.commit_artifact",
        MagicMock(return_value="abc123"),
    )
    add_remote = MagicMock()
    monkeypatch.setattr("backend.projects.service.git_manager.add_remote", add_remote)
    monkeypatch.setattr(
        "backend.projects.service.bootstrap_expansion_node",
        MagicMock(),
    )
    monkeypatch.setattr(
        "backend.projects.service.pipeline_queue.enqueue",
        MagicMock(),
    )

    project = create_project(
        db,
        name="orphan",
        description=None,
        project_doc_content="# orphan\n",
    )

    assert project.remote_url is None
    assert project.github_repo_slug is None
    add_remote.assert_not_called()


def test_create_project_add_remote_failure_is_non_fatal(db, tmp_path, monkeypatch):
    """If git_manager.add_remote raises, the project still gets created
    with the remote_url stored — the user can re-run add_remote later
    via the settings page rather than losing the project entirely."""
    fake_path = str(tmp_path / "repo")
    monkeypatch.setattr(
        "backend.projects.service.git_manager.init_repo",
        MagicMock(return_value=fake_path),
    )
    monkeypatch.setattr(
        "backend.projects.service.git_manager.commit_artifact",
        MagicMock(return_value="abc123"),
    )
    monkeypatch.setattr(
        "backend.projects.service.git_manager.add_remote",
        MagicMock(side_effect=RuntimeError("git not available")),
    )
    monkeypatch.setattr(
        "backend.projects.service.bootstrap_expansion_node",
        MagicMock(),
    )
    monkeypatch.setattr(
        "backend.projects.service.pipeline_queue.enqueue",
        MagicMock(),
    )

    project = create_project(
        db,
        name="haven",
        description=None,
        project_doc_content="# haven\n",
        remote_url="https://github.com/SwaggerAllen/haven.git",
    )

    # Even with the add_remote failure, the project + persisted fields
    # are intact — settings page can retry.
    assert project.remote_url == "https://github.com/SwaggerAllen/haven.git"
    assert project.github_repo_slug == "SwaggerAllen/haven"
