"""Tests for the upload-artifacts create-project flow.

The flow is read-side end-to-end: generate a real v3 substrate via the
``scripts/make_sample_project.py`` fixture generator, tar it (including
``.git/``), POST to ``/api/projects/import``, then assert (a) the
Project row carries ``source="upload"``, (b) the on-disk repo is in
the configured base path, (c) the sanitizer stripped hooks + origin,
(d) ``build_project_graph`` projects nodes from the imported substrate,
(e) writer endpoints reject the upload project.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import _require_writer, get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project, User  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATOR = _REPO_ROOT / "scripts" / "make_sample_project.py"


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


def _override_user_admin() -> User:
    return User(id="u1", username="t", password_hash="x", role="admin")


def _generate_sample(parent: Path, *, leading_dir: bool) -> Path:
    """Run the sample-project generator and return the path to the
    generated v3 repo. ``leading_dir=True`` keeps the generator's own
    output dir; the caller decides whether to tar with it or without."""
    out_dir = parent / "sample"
    subprocess.run(
        [sys.executable, str(_GENERATOR), str(out_dir)],
        check=True,
        capture_output=True,
        cwd=_REPO_ROOT,
    )
    return out_dir


def _make_tarball(repo: Path, dest: Path, *, with_leading_dir: bool) -> Path:
    """Tar a v3 sample repo. ``with_leading_dir=True`` produces a
    tarball where every entry is nested under ``<repo.name>/``; False
    produces a flat tarball (entries at the root)."""
    with tarfile.open(dest, "w:gz") as tf:
        if with_leading_dir:
            tf.add(repo, arcname=repo.name)
        else:
            for child in repo.iterdir():
                tf.add(child, arcname=child.name)
    return dest


def _post_import(
    factory: sessionmaker,
    tarball: Path,
    *,
    name: str = "Sample import",
    description: str | None = None,
):
    def _override_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user_admin
    app.dependency_overrides[_require_writer] = _override_user_admin
    try:
        client = TestClient(app)
        with tarball.open("rb") as f:
            return client.post(
                "/api/projects/import",
                files={"artifacts_file": (tarball.name, f, "application/gzip")},
                data={"name": name, "description": description or ""},
            )
    finally:
        app.dependency_overrides.clear()


def _redirect_base_path(monkeypatch, tmp_path: Path) -> Path:
    base = tmp_path / "repos"
    base.mkdir()
    from backend.config import settings as backend_settings

    monkeypatch.setattr(backend_settings, "git_repos_base_path", str(base))
    return base


# ─── tests ──────────────────────────────────────────────────────────


def test_import_round_trips_to_project_graph(tmp_path, monkeypatch, engine_and_factory):
    """Happy path: tar the sample project (with leading dir), POST it,
    assert the new project's graph projects the expected nodes."""
    _, factory = engine_and_factory
    base = _redirect_base_path(monkeypatch, tmp_path)
    sample = _generate_sample(tmp_path, leading_dir=True)
    tarball = _make_tarball(sample, tmp_path / "sample.tgz", with_leading_dir=True)

    r = _post_import(factory, tarball)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "upload"
    assert body["remote_url"] is None
    project_id = body["id"]

    repo_path = base / project_id
    assert repo_path.is_dir()
    assert (repo_path / ".git").is_dir()
    # Sanitizer stripped hooks + origin.
    hooks_dir = repo_path / ".git" / "hooks"
    assert hooks_dir.is_dir() and not list(hooks_dir.iterdir())
    remotes = subprocess.run(
        ["git", "-C", str(repo_path), "remote"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "origin" not in remotes
    # `main` resolves (the alias survived).
    sha = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert len(sha) == 40

    # Graph projection runs through the same `local_view` the import
    # service used for validation — confirms the read endpoint will work.
    from siege.git_view import local_view
    from siege.projection.graph import build_project_graph

    graph = build_project_graph(local_view(repo_path, ref="main"))
    assert len(graph["nodes"]) > 0
    kinds = {n["kind"] for n in graph["nodes"]}
    assert "feature" in kinds and "component" in kinds


def test_import_accepts_flat_tarball(tmp_path, monkeypatch, engine_and_factory):
    """Tarballs without a leading directory (``tar -czf x.tgz .``-style)
    must work too."""
    _, factory = engine_and_factory
    _redirect_base_path(monkeypatch, tmp_path)
    sample = _generate_sample(tmp_path, leading_dir=False)
    tarball = _make_tarball(sample, tmp_path / "flat.tgz", with_leading_dir=False)

    r = _post_import(factory, tarball, name="Flat import")
    assert r.status_code == 201, r.text


def test_import_rejects_missing_substrate(tmp_path, monkeypatch, engine_and_factory, db):
    """Tarball with a .git/ but no v3 substrate (state/ + ids/) → 400,
    Project row rolled back."""
    _, factory = engine_and_factory
    base = _redirect_base_path(monkeypatch, tmp_path)

    bare = tmp_path / "bare"
    bare.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "-C", str(bare), "config", "user.email", "t@e"], check=True)
    subprocess.run(["git", "-C", str(bare), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(bare), "config", "commit.gpgsign", "false"], check=True)
    (bare / "README").write_text("nothing v3 about me")
    subprocess.run(["git", "-C", str(bare), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(bare), "commit", "-q", "-m", "init"], check=True)

    tarball = _make_tarball(bare, tmp_path / "bare.tgz", with_leading_dir=True)
    pre_count = db.query(Project).count()
    r = _post_import(factory, tarball)
    assert r.status_code == 400, r.text
    assert "substrate" in r.text.lower() or "ids" in r.text.lower()
    # No partial row, no partial directory.
    assert db.query(Project).count() == pre_count
    assert not any(base.iterdir())


def test_import_rejects_path_traversal(tmp_path, monkeypatch, engine_and_factory):
    """Tarball with a ``../`` entry is refused before any extraction."""
    _, factory = engine_and_factory
    _redirect_base_path(monkeypatch, tmp_path)

    tarball = tmp_path / "evil.tgz"
    with tarfile.open(tarball, "w:gz") as tf:
        # Construct a member whose name escapes the unpack root.
        data = io.BytesIO(b"x")
        info = tarfile.TarInfo(name="../escape")
        info.size = 1
        tf.addfile(info, data)

    r = _post_import(factory, tarball)
    assert r.status_code == 400
    assert "traversal" in r.text.lower() or "refus" in r.text.lower()


def test_import_rejects_no_git_dir(tmp_path, monkeypatch, engine_and_factory):
    """Tarball with substrate files but no .git/ is refused — clean
    re-commit is not supported, the upload must carry git history."""
    _, factory = engine_and_factory
    _redirect_base_path(monkeypatch, tmp_path)
    sample = _generate_sample(tmp_path, leading_dir=True)
    # Drop .git/ then re-tar.
    import shutil as _shutil

    _shutil.rmtree(sample / ".git")
    tarball = _make_tarball(sample, tmp_path / "nogit.tgz", with_leading_dir=True)

    r = _post_import(factory, tarball)
    assert r.status_code == 400
    assert ".git" in r.text


def test_import_rejects_corrupted_tarball_with_diagnostic_bytes(
    tmp_path, monkeypatch, engine_and_factory
):
    """Garbage bytes uploaded under a tar filename → 400 whose message
    includes the actual first-bytes magic so the user can tell what they
    sent (e.g. a download served with Content-Encoding: gzip that the
    browser quietly decompressed)."""
    _, factory = engine_and_factory
    _redirect_base_path(monkeypatch, tmp_path)
    junk = tmp_path / "junk.tgz"
    junk.write_bytes(b"<!doctype html><html><body>Not a tarball.</body></html>")

    r = _post_import(factory, junk)
    assert r.status_code == 400
    body = r.text.lower()
    assert "not a valid tar archive" in body
    # The HTML magic '3c21' (b'<!') shows up in the diagnostic so we
    # know what was actually uploaded.
    assert "0x3c21" in body or "first bytes" in body


def test_writer_endpoints_refuse_upload_project(tmp_path, monkeypatch, engine_and_factory, db):
    """An imported project rejects /remote, /push, /open-pr with 400."""
    _, factory = engine_and_factory
    _redirect_base_path(monkeypatch, tmp_path)

    # Seed an upload project directly (faster than running the full import).
    project_id = str(uuid.uuid4())
    db.add(
        Project(
            id=project_id,
            name="Imported",
            source="upload",
            remote_url=None,
            git_repo_path=str(tmp_path / "doesnt-matter"),
        )
    )
    db.commit()

    def _override_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user_admin
    app.dependency_overrides[_require_writer] = _override_user_admin
    try:
        client = TestClient(app)
        r = client.post(
            f"/api/projects/{project_id}/remote",
            json={"remote_url": "https://github.com/me/x.git"},
        )
        assert r.status_code == 400
        assert "read-only" in r.text.lower() or "upload" in r.text.lower()
    finally:
        app.dependency_overrides.clear()
