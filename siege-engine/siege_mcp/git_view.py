"""``GitView`` — per-(project, ref, head_sha) in-memory snapshot.

Every MCP read goes through a ``GitView``. The view:

1. Resolves the project's local bare clone (cloning on first access).
2. Calls ``git fetch`` for the requested ref, debounced per ref.
3. Resolves the ref to a head sha.
4. Materializes a worktree at that sha (cached in-memory by sha).
5. Walks ``state/`` once, parsing every state JSON.
6. Lazy-loads body files via ``read_body`` on first access.

The view is immutable once constructed. The cache is keyed by
``(project, ref, head_sha)`` so a new commit on the same ref produces a
new view; the old view is garbage-collected when its idle TTL expires.

The view is read-only — writes are skills' job. The ``GitWriter`` class
at the bottom is a thin helper that skills (called via the plugin) can
invoke to do `state JSON + body + commit + push` in one shot. It lives
in this module so the read + write code share the same path discipline.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from siege_mcp.config import settings
from siege_mcp.state import (
    ALL_TIERS,
    Scope,
    State,
    Tier,
    sha256_bytes,
)

logger = logging.getLogger(__name__)


class GitViewError(Exception):
    """Raised on git operations that can't be retried automatically."""


@dataclass(frozen=True)
class RefInfo:
    name: str
    head_sha: str
    head_subject: str


@dataclass
class _FetchDebounce:
    last_fetched_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


class _ProjectClone:
    """One per project. Owns the on-disk bare-ish clone + per-ref fetch locks."""

    def __init__(self, project_id: str, base_path: Path) -> None:
        self.project_id = project_id
        self.path = base_path / project_id
        self._fetch_debounce: dict[str, _FetchDebounce] = {}
        self._fetch_lock = threading.Lock()

    def _debounce_for(self, ref: str) -> _FetchDebounce:
        with self._fetch_lock:
            d = self._fetch_debounce.get(ref)
            if d is None:
                d = _FetchDebounce()
                self._fetch_debounce[ref] = d
            return d

    def ensure_cloned(self, remote_url: str | None, access_token: str | None = None) -> None:
        if (self.path / ".git").exists():
            return
        if not remote_url:
            raise GitViewError(
                f"Project {self.project_id} clone missing and no remote_url provided"
            )
        # For HTTPS GitHub URLs, inject the OAuth token into the URL
        # so the clone authenticates against private repos. Git stores
        # the credentialed URL in `.git/config` so subsequent `git
        # fetch origin` calls reuse the same auth — no separate
        # credential helper needed. The token sits on the container's
        # filesystem at /data/repos/<project>/.git/config; that's
        # acceptable for v0 (single-tenant droplet, claude-user
        # ownership).
        clone_url = _maybe_inject_token(remote_url, access_token)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_git(["clone", clone_url, str(self.path)], cwd=None)
        except GitViewError as exc:
            # Sanitize the error in case the credentialed URL leaked
            # into the stderr message — git usually scrubs it, but be
            # defensive.
            scrubbed = (
                str(exc).replace(clone_url, remote_url) if clone_url != remote_url else str(exc)
            )
            if access_token is None and "could not read Username" in scrubbed:
                raise GitViewError(
                    f"Clone of {remote_url} requires authentication. "
                    "Connect your GitHub account on Project Settings → GitHub connection "
                    "and retry, or make the repository public."
                ) from exc
            raise GitViewError(scrubbed) from exc

    def fetch_ref(self, ref: str) -> None:
        debounce = self._debounce_for(ref)
        with debounce.lock:
            now = time.monotonic()
            if now - debounce.last_fetched_at < settings.git_fetch_debounce_seconds:
                return
            try:
                run_git(["fetch", "origin", ref], cwd=self.path)
            except GitViewError as exc:
                logger.warning("git fetch failed for %s/%s: %s", self.project_id, ref, exc)
                raise
            debounce.last_fetched_at = now

    def resolve_ref(self, ref: str) -> str:
        """Return the head sha for a ref (after fetch)."""
        out = run_git(["rev-parse", f"origin/{ref}"], cwd=self.path).strip()
        if not out:
            raise GitViewError(f"Could not resolve ref {ref!r} for project {self.project_id}")
        return out

    def list_refs(self) -> list[RefInfo]:
        """List remote branches with their head sha + subject."""
        run_git(["fetch", "origin", "--prune"], cwd=self.path)
        out = run_git(
            [
                "for-each-ref",
                "refs/remotes/origin",
                "--format=%(refname:short)\t%(objectname)\t%(contents:subject)",
            ],
            cwd=self.path,
        )
        refs: list[RefInfo] = []
        for line in out.splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 2:
                continue
            name, sha = parts[0], parts[1]
            subject = parts[2] if len(parts) == 3 else ""
            if name.endswith("/HEAD"):
                continue
            # Strip leading "origin/" to match what callers pass back.
            local_name = name.split("/", 1)[1] if name.startswith("origin/") else name
            refs.append(RefInfo(name=local_name, head_sha=sha, head_subject=subject))
        return refs

    def show_blob(self, sha: str, path: str) -> bytes:
        """Read a path's bytes at a given commit sha. Raises if missing."""
        result = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=self.path,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise GitViewError(
                f"git show {sha}:{path} failed: {result.stderr.decode('utf-8', 'replace').strip()}"
            )
        return result.stdout

    def ls_tree(self, sha: str, prefix: str) -> list[str]:
        """List files under prefix in the tree at sha. Paths are repo-relative."""
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", sha, prefix],
            cwd=self.path,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            # Empty tree (the prefix doesn't exist yet) is not an error.
            stderr = result.stderr.decode("utf-8", "replace")
            if "exists on disk, but not in" in stderr or "Not a valid object name" in stderr:
                return []
            raise GitViewError(f"git ls-tree failed: {stderr.strip()}")
        return [line for line in result.stdout.decode("utf-8").splitlines() if line]


def _maybe_inject_token(remote_url: str, access_token: str | None) -> str:
    """For an https://github.com/... URL, inject the OAuth token as basic auth.

    Returns the URL unchanged when the token is empty, the URL isn't
    https, or the URL already has credentials in it.
    """
    if not access_token:
        return remote_url
    if not remote_url.startswith("https://"):
        return remote_url
    # Don't double-inject if the URL already has @ credentials.
    after_scheme = remote_url[len("https://") :]
    if "@" in after_scheme.split("/", 1)[0]:
        return remote_url
    return f"https://x-access-token:{access_token}@" + after_scheme


def run_git(args: list[str], cwd: Path | None) -> str:
    """Run a git subcommand and return stdout. Raises ``GitViewError`` on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise GitViewError(
            f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout.decode("utf-8")


class GitView:
    """In-memory snapshot of a project's git tree at a specific (ref, sha).

    Construction does the fetch + tree-walk. Bodies are lazy.
    """

    def __init__(self, clone: _ProjectClone, ref: str, head_sha: str) -> None:
        self.clone = clone
        self.ref = ref
        self.head_sha = head_sha
        self._states: dict[tuple[str, ...], State] = {}
        self._bodies: dict[str, bytes] = {}
        self._loaded_at = time.monotonic()
        self._load_all_state()

    def _load_all_state(self) -> None:
        """Walk state/ once and parse every JSON into the index."""
        for path in self.clone.ls_tree(self.head_sha, "state/"):
            if not path.endswith(".json"):
                continue
            try:
                raw = self.clone.show_blob(self.head_sha, path).decode("utf-8")
                import json

                state = self._parse_state_with_recovery(json.loads(raw))
            except Exception as exc:  # noqa: BLE001 — log + skip malformed
                logger.warning("Skipping malformed state file %s: %s", path, exc)
                continue
            if state is not None:
                self._states[state.scope.key()] = state

    def _parse_state_with_recovery(self, raw: dict) -> State | None:
        """Parse a state dict; return None if it's recognizably-corrupt."""
        from siege_mcp.state import parse_state

        try:
            return parse_state(raw)
        except (KeyError, ValueError) as exc:
            logger.warning("State JSON failed validation: %s", exc)
            return None

    # ------------ Read API ------------

    def get_state(self, scope: Scope) -> State | None:
        return self._states.get(scope.key())

    def list_tier(self, tier: Tier) -> list[State]:
        return sorted(
            (s for s in self._states.values() if s.scope.tier == tier),
            key=lambda s: (s.scope.parent_id or "", s.scope.sub_id or "", s.scope.comp_id or ""),
        )

    def all_states(self) -> Iterator[State]:
        yield from self._states.values()

    def read_body(self, path: str) -> bytes:
        """Read a body file lazily, caching the result."""
        cached = self._bodies.get(path)
        if cached is not None:
            return cached
        data = self.clone.show_blob(self.head_sha, path)
        self._bodies[path] = data
        return data

    def read_body_text(self, path: str) -> str:
        return self.read_body(path).decode("utf-8")

    def body_sha256(self, path: str) -> str:
        return sha256_bytes(self.read_body(path))

    def drift_for(self, state: State) -> dict[str, str] | None:
        """Return a drift descriptor if the body's actual sha doesn't match state JSON."""
        if not state.draft:
            return None
        try:
            actual = self.body_sha256(state.draft.body_path)
        except GitViewError:
            return {"kind": "missing_body", "expected": state.draft.body_sha256}
        if actual != state.draft.body_sha256:
            return {
                "kind": "sha_mismatch",
                "expected": state.draft.body_sha256,
                "actual": actual,
            }
        return None

    # ------------ Convenience ------------

    def states_by_tier(self) -> dict[Tier, list[State]]:
        out: dict[Tier, list[State]] = {tier: [] for tier in ALL_TIERS}
        for s in self._states.values():
            out[s.scope.tier].append(s)
        return out


# ---------------- Multi-project cache ----------------


class GitViewCache:
    """Per-process cache. Hands out GitViews keyed by (project, ref, head_sha)."""

    def __init__(self) -> None:
        self._clones: dict[str, _ProjectClone] = {}
        self._views: dict[tuple[str, str, str], GitView] = {}
        self._last_touch: dict[tuple[str, str, str], float] = {}
        self._lock = threading.Lock()

    def get_view(
        self,
        project_id: str,
        ref: str,
        remote_url: str | None = None,
        access_token: str | None = None,
    ) -> GitView:
        clone = self._get_or_make_clone(project_id, remote_url, access_token)
        clone.fetch_ref(ref)
        head_sha = clone.resolve_ref(ref)
        key = (project_id, ref, head_sha)
        with self._lock:
            view = self._views.get(key)
            self._last_touch[key] = time.monotonic()
            if view is None:
                view = GitView(clone, ref, head_sha)
                self._views[key] = view
            self._evict_idle_locked()
        return view

    def list_refs(
        self,
        project_id: str,
        remote_url: str | None = None,
        access_token: str | None = None,
    ) -> list[RefInfo]:
        clone = self._get_or_make_clone(project_id, remote_url, access_token)
        return clone.list_refs()

    def _get_or_make_clone(
        self,
        project_id: str,
        remote_url: str | None,
        access_token: str | None = None,
    ) -> _ProjectClone:
        with self._lock:
            clone = self._clones.get(project_id)
            if clone is None:
                base = Path(settings.git_repos_base_path)
                clone = _ProjectClone(project_id, base)
                self._clones[project_id] = clone
        clone.ensure_cloned(remote_url, access_token=access_token)
        return clone

    def _evict_idle_locked(self) -> None:
        now = time.monotonic()
        ttl = settings.git_view_idle_ttl_seconds
        stale = [k for k, t in self._last_touch.items() if now - t > ttl]
        for k in stale:
            self._views.pop(k, None)
            self._last_touch.pop(k, None)


# Process-wide singleton. The MCP server is single-process, so this is fine.
cache = GitViewCache()
