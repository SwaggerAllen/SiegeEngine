"""Local helpers + thin HTTP client for the legacy siege backend.

Most siege CLI write subcommands operate purely on the local repo
— they edit body files, commit, push, and let the deployed
backend pick state changes up through its git-fetcher on the next
read. The v3 substrate model for refs / vocab / input documents
is slightly different: body lives in git, but the backend needs
to be told "a new doc exists, here's its body_sha + role" so its
state projections update.

This module exists to issue those notifications. It's deliberately
stdlib-only (urllib) so the ``[read]`` extra doesn't have to grow
new dependencies — install with ``pip install siege-engine[read]``
and these calls still work.

Authentication: ``SIEGE_TOKEN`` env var carries a JWT issued by the
dashboard's login flow (see the dev-token panel at
``/cheatsheet``). The backend URL defaults to
``https://siege.strutco.io`` and is overridable via
``SIEGE_API_BASE``.

Failures surface as ``BackendError`` with the HTTP status + body
so callers can pattern-match the user-visible error.
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Any

# Crockford base32 — matches backend.graph.ids._CROCKFORD so locally-minted
# ids round-trip cleanly through the server's id-grammar validator.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ID_SUFFIX_LENGTH = 8


def mint_id(prefix: str) -> str:
    """Mint a fresh ``<prefix>_<Crockford-base32>`` id.

    Used by CLI subcommands that need a stable id before the
    server has minted one (e.g. ``create-ref`` writes a body file
    at ``refs/<ref_id>/body.md`` and needs the id pre-commit). The
    server validates the id grammar on accept.
    """
    suffix = "".join(secrets.choice(_CROCKFORD) for _ in range(_ID_SUFFIX_LENGTH))
    return f"{prefix}_{suffix}"


class BackendError(RuntimeError):
    """Raised when a backend request fails.

    ``status`` carries the HTTP status code (or ``None`` for
    network / transport errors). ``body`` carries the response
    body text (or the error message for transport failures).
    """

    def __init__(self, status: int | None, body: str) -> None:
        self.status = status
        self.body = body
        suffix = f" (status {status})" if status is not None else ""
        super().__init__(f"backend request failed{suffix}: {body[:500]}")


def _api_base() -> str:
    base = os.environ.get("SIEGE_API_BASE", "https://siege.strutco.io").rstrip("/")
    return base


def _token() -> str:
    tok = os.environ.get("SIEGE_TOKEN", "")
    if not tok:
        raise BackendError(
            None,
            "SIEGE_TOKEN env var not set. Get one from the cheat sheet "
            "page's dev-token panel and export it before retrying.",
        )
    return tok


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    url = _api_base() + path
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BackendError(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise BackendError(None, str(exc)) from exc


def post(path: str, payload: dict[str, Any]) -> Any:
    return _request("POST", path, payload)


def get(path: str) -> Any:
    return _request("GET", path)


# ── Input documents ──────────────────────────────────────────────────


def create_input_document(
    project_id: str,
    role: str,
    name: str,
    body_sha: str,
    body_path: str | None = None,
) -> dict[str, Any]:
    """Register a git-resident input document on the backend.

    Caller has already written the body to ``body_path`` in the
    project repo and pushed the commit. This call updates the
    backend's projection.
    """
    payload: dict[str, Any] = {
        "role": role,
        "name": name,
        "body_sha": body_sha,
    }
    if body_path is not None:
        payload["body_path"] = body_path
    return post(f"/api/projects/{project_id}/input-documents", payload)


def list_input_documents(project_id: str) -> list[dict[str, Any]]:
    resp = get(f"/api/projects/{project_id}/input-documents")
    return resp.get("input_documents", []) if isinstance(resp, dict) else []


# ── References ───────────────────────────────────────────────────────


def create_git_reference(
    project_id: str,
    ref_id: str,
    name: str,
    body_sha: str,
    body_path: str | None = None,
) -> dict[str, Any]:
    """Register a git-resident ref on the backend.

    Caller has already minted the ref id, written the body to
    ``body_path`` in the project repo, and pushed the commit.
    """
    payload: dict[str, Any] = {
        "ref_id": ref_id,
        "name": name,
        "body_sha": body_sha,
    }
    if body_path is not None:
        payload["body_path"] = body_path
    return post(f"/api/projects/{project_id}/references", payload)


def get_reference_by_name(project_id: str, name: str) -> dict[str, Any] | None:
    """Look up a ref by name; returns ``None`` if absent."""
    from urllib.parse import quote

    return get(f"/api/projects/{project_id}/references/by-name?name={quote(name)}")


def list_references(project_id: str) -> list[dict[str, Any]]:
    """List all refs in a project (read uses the legacy endpoint
    that returns both legacy and v3 refs uniformly)."""
    resp = get(f"/api/projects/{project_id}/references")
    return resp.get("references", []) if isinstance(resp, dict) else []


# ── Vocabulary ───────────────────────────────────────────────────────


def create_git_vocab(
    project_id: str,
    vocab_id: str,
    name: str,
    body_sha: str,
    body_path: str | None = None,
) -> dict[str, Any]:
    """Register a git-resident vocab entry on the backend."""
    payload: dict[str, Any] = {
        "vocab_id": vocab_id,
        "name": name,
        "body_sha": body_sha,
    }
    if body_path is not None:
        payload["body_path"] = body_path
    return post(f"/api/projects/{project_id}/vocabulary", payload)


def get_vocab_by_name(project_id: str, name: str) -> dict[str, Any] | None:
    from urllib.parse import quote

    return get(f"/api/projects/{project_id}/vocabulary/by-name?name={quote(name)}")


def list_vocab(project_id: str) -> list[dict[str, Any]]:
    resp = get(f"/api/projects/{project_id}/vocabulary")
    return resp.get("entries", []) if isinstance(resp, dict) else []
