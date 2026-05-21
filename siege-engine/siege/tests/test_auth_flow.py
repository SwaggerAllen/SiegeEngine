"""Tests for the per-request auth flow: contextvar + token injection.

Two contracts under test:

1. ``_maybe_inject_token`` mints a ``https://x-access-token:TOKEN@...``
   URL from an https GitHub URL + an OAuth token, and leaves other
   URL shapes alone.
2. ``user_id_context`` binds the user id for the scope of the with-
   block; ``current_user_id`` reads it; the binding doesn't leak after
   the block exits.
"""

from __future__ import annotations

import pytest

from siege.auth_context import current_user_id, user_id_context
from siege.git_view import _maybe_inject_token


@pytest.mark.parametrize(
    "url,token,expected",
    [
        (
            "https://github.com/SwaggerAllen/haven.git",
            "ghs_abc123",
            "https://x-access-token:ghs_abc123@github.com/SwaggerAllen/haven.git",
        ),
        (
            "https://github.com/SwaggerAllen/haven",
            "ghs_xyz",
            "https://x-access-token:ghs_xyz@github.com/SwaggerAllen/haven",
        ),
        # No token → pass through.
        (
            "https://github.com/SwaggerAllen/haven.git",
            None,
            "https://github.com/SwaggerAllen/haven.git",
        ),
        (
            "https://github.com/SwaggerAllen/haven.git",
            "",
            "https://github.com/SwaggerAllen/haven.git",
        ),
        # SSH URL → token doesn't apply.
        (
            "git@github.com:SwaggerAllen/haven.git",
            "ghs_abc",
            "git@github.com:SwaggerAllen/haven.git",
        ),
        # Already-credentialed URL → leave it alone.
        (
            "https://x-access-token:OLD@github.com/SwaggerAllen/haven.git",
            "NEW",
            "https://x-access-token:OLD@github.com/SwaggerAllen/haven.git",
        ),
        # Non-GitHub https → still gets the token; works for any
        # provider that accepts basic auth with this user form.
        (
            "https://gitlab.com/foo/bar.git",
            "ghs_abc",
            "https://x-access-token:ghs_abc@gitlab.com/foo/bar.git",
        ),
    ],
)
def test_maybe_inject_token(url, token, expected):
    assert _maybe_inject_token(url, token) == expected


def test_user_id_context_binds_and_resets():
    assert current_user_id() is None
    with user_id_context("user_a"):
        assert current_user_id() == "user_a"
        with user_id_context("user_b"):
            assert current_user_id() == "user_b"
        assert current_user_id() == "user_a"
    assert current_user_id() is None


def test_user_id_context_none_is_a_valid_binding():
    """An unauthenticated request still wants to clear any leftover
    binding from a previous request on the same task."""
    with user_id_context("user_a"):
        with user_id_context(None):
            assert current_user_id() is None
        assert current_user_id() == "user_a"
