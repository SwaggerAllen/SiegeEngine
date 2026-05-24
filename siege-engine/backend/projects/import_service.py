"""Project import — materialize a v3 substrate from an uploaded tarball.

Companion to ``create_project`` for the upload-artifacts create flow.
The user uploads a tarball of their project directory (including
``.git/``); we unpack it under ``${git_repos_base_path}/<project_id>/``,
sanitize the resulting repo (strip hooks, remove the user's origin),
ensure a ``main`` branch exists so the dashboard's default ref
resolves, and validate that the working tree actually contains v3
substrate. The Project row carries ``source="upload"`` and
``remote_url=None``; the writer endpoints refuse it (see
``routes._require_writable``).

The unpack is strict: per-entry traversal / symlink checks, an
aggregate size cap. Failures roll back the on-disk dir and the
Project row, so a rejected upload leaves no trace.
"""

from __future__ import annotations

import configparser
import logging
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import IO

from sqlalchemy.orm import Session

from backend.config import settings as backend_settings
from backend.models import Project
from siege.git_view import local_view
from siege.projection.graph import build_project_graph

logger = logging.getLogger(__name__)

# Defense-in-depth cap on uncompressed extraction. Real v3 substrates
# (bodies + state JSON + identity ledgers + .git/) are at most a few MB;
# 50 MB leaves plenty of headroom while bounding a malicious payload.
_MAX_EXTRACTED_BYTES = 50 * 1024 * 1024


class ImportError(ValueError):
    """Raised on import failures the route should surface as 400."""


def import_project(
    db: Session,
    name: str,
    description: str | None,
    artifacts_stream: IO[bytes],
    filename: str | None = None,
) -> Project:
    """Create a Project from an uploaded artifact tarball/zip.

    Raises ``ImportError`` if the archive shape is wrong, the substrate
    is missing, or the unpacked repo can't be projected. On any failure
    the on-disk directory and the Project row are rolled back.
    """
    project = Project(
        name=name,
        description=description,
        remote_url=None,
        github_repo_slug=None,
        auto_push_enabled=False,
        source="upload",
        git_repo_path="",
    )
    db.add(project)
    db.flush()  # mint the id without committing yet
    project_id = project.id
    repo_path = Path(backend_settings.git_repos_base_path) / project_id

    try:
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        _extract(artifacts_stream, repo_path, filename)
        _flatten_single_top_dir(repo_path)
        if not (repo_path / ".git").is_dir():
            raise ImportError(
                "Uploaded archive doesn't contain a .git directory at the root. "
                "Tar your project directory (`tar -czf out.tgz <project>/`) so .git/ is included."
            )
        _sanitize_repo(repo_path)
        _ensure_main_branch(repo_path)
        _validate_substrate(repo_path)
        project.git_repo_path = str(repo_path)
        db.commit()
        db.refresh(project)
        return project
    except Exception:
        # Roll back the on-disk dir and the Project row together.
        shutil.rmtree(repo_path, ignore_errors=True)
        db.rollback()
        # Project was only flushed, not committed — rollback drops it
        # from the session. Belt-and-braces: explicit delete if it's
        # still present (some session configs may persist it).
        if project in db:
            db.delete(project)
            db.commit()
        raise


# ---------------- extraction ----------------


def _extract(stream: IO[bytes], dest: Path, filename: str | None) -> None:
    """Unpack the uploaded archive into ``dest`` with safety checks."""
    dest.mkdir(parents=True, exist_ok=False)
    name = (filename or "").lower()
    if name.endswith(".zip"):
        _extract_zip(stream, dest)
    else:
        # Default to tar — ``tarfile.open(mode="r|*")`` auto-detects
        # gz/bz2/xz/plain.
        _extract_tar(stream, dest)


def _extract_tar(stream: IO[bytes], dest: Path) -> None:
    # Defensive — Starlette's UploadFile may or may not have its
    # underlying file at position 0 by the time the route handler runs.
    try:
        stream.seek(0)
    except (OSError, AttributeError):
        pass
    try:
        # ``r:*`` (seekable, transparent compression) is more robust
        # than the streaming ``r|*`` variant — random-access reads on
        # the SpooledTemporaryFile underlying UploadFile, auto-detects
        # gz / bz2 / xz from the file magic.
        tf = tarfile.open(fileobj=stream, mode="r:*")
    except tarfile.TarError as exc:
        raise ImportError(_tar_open_error_msg(stream, exc)) from exc
    total = 0
    try:
        for member in tf:
            _check_member(member.name, member.issym(), member.islnk(), member.size)
            total += max(int(member.size), 0)
            if total > _MAX_EXTRACTED_BYTES:
                raise ImportError(
                    f"Archive exceeds the {_MAX_EXTRACTED_BYTES // (1024 * 1024)} MB"
                    " extracted size cap."
                )
            tf.extract(member, dest)
    finally:
        tf.close()


def _tar_open_error_msg(stream: IO[bytes], exc: tarfile.TarError) -> str:
    """Build a diagnosable error for a failed ``tarfile.open``.

    Surfaces the first few bytes (so we can tell gzip vs zip vs random
    junk) and the byte length, since the bare ``invalid header`` from
    tarfile gives the user no clue what they actually uploaded.
    """
    head_hex = ""
    size_hint = ""
    try:
        stream.seek(0)
        head = stream.read(8) or b""
        head_hex = head.hex()
    except (OSError, AttributeError):
        pass
    try:
        stream.seek(0, 2)
        size_hint = f", {stream.tell()} bytes"
    except (OSError, AttributeError):
        pass
    finally:
        try:
            stream.seek(0)
        except (OSError, AttributeError):
            pass
    hint = ""
    if head_hex.startswith("504b"):
        hint = " — looks like a zip; rename the upload to .zip."
    elif head_hex.startswith("1f8b"):
        hint = " — gzip magic is correct, so the inner tar is malformed."
    logger.warning("tar open failed: %s; head=0x%s%s", exc, head_hex, size_hint)
    return (
        f"Not a valid tar archive: {exc}. First bytes: 0x{head_hex or '<unreadable>'}"
        f"{size_hint}.{hint}"
    )


def _extract_zip(stream: IO[bytes], dest: Path) -> None:
    total = 0
    try:
        zf = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise ImportError(f"Not a valid zip archive: {exc}") from exc
    try:
        for info in zf.infolist():
            _check_member(info.filename, False, False, info.file_size)
            total += int(info.file_size)
            if total > _MAX_EXTRACTED_BYTES:
                raise ImportError(
                    f"Archive exceeds the {_MAX_EXTRACTED_BYTES // (1024 * 1024)} MB"
                    " extracted size cap."
                )
        zf.extractall(dest)
    finally:
        zf.close()


def _check_member(member_name: str, is_sym: bool, is_link: bool, size: int) -> None:
    if is_sym or is_link:
        raise ImportError(f"Archive contains a symlink/hardlink ({member_name!r}); refusing.")
    p = Path(member_name)
    if p.is_absolute():
        raise ImportError(f"Archive contains an absolute path ({member_name!r}); refusing.")
    parts = p.parts
    if ".." in parts:
        raise ImportError(f"Archive contains a path-traversal entry ({member_name!r}); refusing.")
    if size < 0:
        raise ImportError(f"Archive member {member_name!r} has a negative size; refusing.")


def _flatten_single_top_dir(dest: Path) -> None:
    """If the archive nested everything under one top dir (a common tar
    habit: ``tar -czf x.tgz project/``), move its contents up so the
    on-disk root is the repo root. Idempotent — does nothing when the
    layout is already flat.
    """
    entries = [p for p in dest.iterdir() if not p.name.startswith(".")]
    hidden = [p for p in dest.iterdir() if p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir() and not hidden:
        inner = entries[0]
        for child in list(inner.iterdir()):
            shutil.move(str(child), str(dest / child.name))
        inner.rmdir()


# ---------------- sanitize ----------------


def _sanitize_repo(repo: Path) -> None:
    """Strip artifacts we don't want the server inheriting from the
    uploader's .git/ — hooks (no server-side execution), the origin
    remote (no fetches against the user's actual GitHub), and the
    ``[user]`` config section (defensive — our commits would use our
    own identity, but uploads shouldn't write either way)."""
    hooks = repo / ".git" / "hooks"
    if hooks.exists():
        shutil.rmtree(hooks, ignore_errors=True)
    # Recreate as an empty dir so any tooling that expects it to exist
    # doesn't choke.
    hooks.mkdir(exist_ok=True)

    # Drop origin if present. Ignore the failure when no origin exists.
    subprocess.run(
        ["git", "-C", str(repo), "remote", "remove", "origin"],
        check=False,
        capture_output=True,
    )

    # Strip [user] from .git/config.
    config_path = repo / ".git" / "config"
    if config_path.exists():
        cp = configparser.ConfigParser(strict=False)
        try:
            cp.read(config_path)
        except configparser.Error:
            # Unparseable config — leave it alone rather than corrupting.
            return
        if cp.has_section("user"):
            cp.remove_section("user")
            with config_path.open("w") as f:
                cp.write(f)


def _ensure_main_branch(repo: Path) -> None:
    """Make sure ``main`` resolves to the imported HEAD.

    Reads ``.git/HEAD``. If it's a symbolic ref to ``refs/heads/main``,
    nothing to do. If it's a symbolic ref to some other branch, create
    a ``main`` ref pointing at HEAD (alias, not a rename — the user's
    original branch stays intact). If HEAD is detached (a raw sha),
    refuse with an actionable error.
    """
    head_file = repo / ".git" / "HEAD"
    if not head_file.exists():
        raise ImportError("Uploaded repo has no .git/HEAD; not a valid git repo.")
    head_content = head_file.read_text().strip()
    if not head_content.startswith("ref: "):
        raise ImportError(
            "Uploaded repo has a detached HEAD. Check out a branch (e.g. `git switch -c main`) "
            "and re-upload."
        )
    branch_ref = head_content[len("ref: ") :].strip()
    if branch_ref == "refs/heads/main":
        return
    # Resolve HEAD to a sha and update refs/heads/main if it doesn't exist.
    try:
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ImportError(
            "Uploaded repo's HEAD doesn't resolve to a commit. Make sure the branch "
            "has at least one commit."
        ) from exc
    main_ref = repo / ".git" / "refs" / "heads" / "main"
    if main_ref.exists():
        return  # the uploader already had a `main` — leave it alone
    main_ref.parent.mkdir(parents=True, exist_ok=True)
    main_ref.write_text(head_sha + "\n")


def _validate_substrate(repo: Path) -> None:
    """Run the v3 graph projection on the unpacked repo. If it raises
    or returns no nodes, the upload doesn't contain a usable substrate."""
    try:
        view = local_view(repo, ref="main")
        graph = build_project_graph(view)
    except Exception as exc:
        raise ImportError(f"Uploaded repo doesn't project as a v3 substrate: {exc}") from exc
    if not graph.get("nodes"):
        raise ImportError(
            "Uploaded repo has no v3 substrate nodes at HEAD — expected feature_expansion / "
            "requirements / sysarch identity ledgers under `ids/`."
        )
