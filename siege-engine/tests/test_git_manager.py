"""Regression tests for ``backend.git_manager.service.GitManager``.

The bug these lock in: ``commit_artifact`` used to call
``repo.index.diff("HEAD")`` unconditionally to check whether the
staged content actually differed from the prior commit. On a fresh
repo created by ``init_repo``, there is no prior commit and ``HEAD``
doesn't resolve, so the call raised ``gitdb.exc.BadName: Ref 'HEAD'
did not resolve to an object`` — which bubbled up as a 500 when the
frontend tried to create a new project.

The fix is to skip the diff check when ``repo.head.is_valid()`` is
False and go straight to the commit path.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.git_manager.service import GitManager, git_manager


@pytest.fixture()
def isolated_git_base(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "git_repos_base_path", str(tmp_path))
    monkeypatch.setattr(git_manager, "base_path", tmp_path)
    return tmp_path


def test_commit_artifact_on_fresh_repo_creates_initial_commit(isolated_git_base):
    """First commit on a fresh repo must not crash on missing HEAD."""
    pid = "proj_fresh"
    git_manager.init_repo(pid)
    sha = git_manager.commit_artifact(
        pid,
        "# Hello\n\nSome content.",
        "project_doc.md",
        "Initial project document",
    )
    assert sha and len(sha) == 40


def test_commit_artifact_subsequent_commits_still_dedupe(isolated_git_base):
    """After the initial commit, unchanged content must still no-op."""
    pid = "proj_dedupe"
    git_manager.init_repo(pid)
    sha_first = git_manager.commit_artifact(pid, "hello\n", "a.md")

    # Second call with the same content should return the prior SHA,
    # not create an empty commit.
    sha_second = git_manager.commit_artifact(pid, "hello\n", "a.md")
    assert sha_second == sha_first

    # Third call with changed content should create a new commit.
    sha_third = git_manager.commit_artifact(pid, "hello world\n", "a.md")
    assert sha_third != sha_first


def test_commit_artifact_ignores_stale_lock_on_fresh_repo(isolated_git_base):
    """Stale index.lock on a fresh repo gets cleaned up, not fatal."""
    from pathlib import Path

    pid = "proj_stale_lock"
    path = git_manager.init_repo(pid)

    # Drop a fake index.lock to simulate a crashed prior process
    lock = Path(path) / ".git" / "index.lock"
    lock.write_text("")
    assert lock.exists()

    sha = git_manager.commit_artifact(pid, "x", "x.md")
    assert sha
    assert not lock.exists()


def test_git_manager_can_be_instantiated_with_explicit_base(tmp_path):
    """GitManager accepts an explicit base_path override."""
    gm = GitManager(base_path=str(tmp_path))
    assert gm.base_path == tmp_path
