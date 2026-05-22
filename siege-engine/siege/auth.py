"""JWT verification ported from ``backend/auth/service.py``.

The MCP server is read-only and doesn't issue new tokens — that's still
the existing dashboard's job. This module only verifies tokens the
dashboard (or a future CC auth handoff) presents.

Password hashing isn't ported: the MCP server never sees passwords.
Login + token issuance stays on the existing FastAPI auth surface
during the migration and gets folded back into this module only if /
when the old backend is fully retired.
"""

from __future__ import annotations

from typing import Any

from jose import JWTError, jwt

from siege.config import settings


class AuthError(Exception):
    """Raised when a token is missing, malformed, or expired."""


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT, returning the claims payload.

    Raises ``AuthError`` on any failure so callers don't have to know
    about ``jose.JWTError``.
    """
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc


def extract_bearer(header_value: str | None) -> str:
    """Pull the bearer token from an ``Authorization: Bearer <token>`` header."""
    if not header_value:
        raise AuthError("Missing Authorization header")
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization header must be 'Bearer <token>'")
    return parts[1]


def verify_request_token(header_value: str | None) -> dict[str, Any]:
    """Convenience for FastAPI dependencies — combines extract + decode."""
    return decode_token(extract_bearer(header_value))
