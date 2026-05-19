"""Backend DB lookups for project remotes + per-user GitHub tokens.

This module reaches into the legacy ``backend.*`` modules to read the
two things siege_mcp needs at request time:

- ``Project.remote_url`` — the clone URL for the project's GitHub repo.
  Set at project creation or via the settings panel; lives on the
  Project row.
- ``GitHubCredential.access_token`` — the per-user OAuth token. Set
  when the user completes the "Connect GitHub" flow.

Both lookups are optional — if either is missing, the caller proceeds
without auth (which works for public repos and for read-only
operations against an already-cloned repo).

Once Phase 4 deletes the legacy backend, this module gets rewritten
to read the same data from siege_mcp's own state files. For the
migration window the cross-import is the pragmatic shape.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ProjectAuth(NamedTuple):
    remote_url: str | None
    access_token: str | None


def lookup_project_auth(project_id: str, user_id: str | None) -> ProjectAuth:
    """Return (remote_url, access_token) for a (project, user) pair.

    Both values may be None. The caller is responsible for surfacing a
    sensible error if a clone needs the remote_url but it's missing,
    or if a private-repo clone needs the token but it's missing.

    The DB session is short-lived — opened, queried, closed — so we
    don't compete with the live FastAPI request handlers for the
    SQLite write lock.
    """
    try:
        # Import here so a fresh `siege_mcp` install without the
        # legacy backend (e.g. once Phase 4 deletion lands) doesn't
        # blow up at module load time.
        from backend.database import SessionLocal
        from backend.models import GitHubCredential, Project
    except Exception as exc:  # noqa: BLE001
        logger.warning("Backend models unavailable for auth lookup: %s", exc)
        return ProjectAuth(None, None)

    session = SessionLocal()
    try:
        remote_url: str | None = None
        access_token: str | None = None

        project = session.get(Project, project_id)
        if project:
            remote_url = project.remote_url

        if user_id:
            cred = session.query(GitHubCredential).filter_by(user_id=user_id).first()
            if cred:
                access_token = cred.access_token

        return ProjectAuth(remote_url=remote_url, access_token=access_token)
    finally:
        session.close()
