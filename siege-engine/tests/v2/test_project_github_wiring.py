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

from backend.projects.service import derive_github_slug  # noqa: E402


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
