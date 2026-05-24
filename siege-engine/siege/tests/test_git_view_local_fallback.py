"""Tests for ``_ProjectClone``'s remote-less ref handling.

Upload-imported projects land on disk without a remote — the import
sanitizer strips ``origin`` so the server can't accidentally reach the
user's real GitHub. ``_ProjectClone`` has to cope: ``fetch_ref`` should
noop and ``resolve_ref`` should fall back to the local branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from siege.git_view import _ProjectClone


def _init_local_repo(repo: Path) -> str:
    """Init a remote-less repo with one commit on ``main``. Returns the sha."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)
    (repo / "README").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_resolve_ref_falls_back_to_local_branch(tmp_path):
    base = tmp_path / "repos"
    base.mkdir()
    sha = _init_local_repo(base / "proj-1")

    clone = _ProjectClone("proj-1", base)
    assert clone.resolve_ref("main") == sha


def test_fetch_ref_noops_with_no_origin(tmp_path):
    """No remote configured → no `git fetch` invocation, no exception."""
    base = tmp_path / "repos"
    base.mkdir()
    _init_local_repo(base / "proj-1")

    clone = _ProjectClone("proj-1", base)
    clone.fetch_ref("main")  # would raise if run_git tried to fetch from nothing


def test_resolve_ref_raises_when_neither_ref_resolves(tmp_path):
    base = tmp_path / "repos"
    base.mkdir()
    _init_local_repo(base / "proj-1")

    clone = _ProjectClone("proj-1", base)
    try:
        clone.resolve_ref("nonexistent-branch")
    except Exception as exc:
        assert "nonexistent-branch" in str(exc)
    else:
        raise AssertionError("expected resolve_ref to raise for an unknown ref")
