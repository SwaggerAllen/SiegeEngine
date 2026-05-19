"""Per-request auth context for siege_mcp tool calls.

When an MCP tool runs, it needs to know which user is calling so it
can look up that user's GitHub OAuth token for a private-repo clone.
The user identity comes from the JWT verified at the HTTP layer; we
stash it in a ContextVar so the tool functions (which run on the
same thread/task as the request) can read it without changing every
tool signature.

This is deliberately ONE-WAY: the server.py request handler sets the
var, the tool functions read it. Clients cannot influence the value
via the tool arguments — preventing a malicious caller from passing
``user_id="someone-else"`` to act as another user.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_current_user_id: ContextVar[str | None] = ContextVar("siege_mcp.current_user_id", default=None)


@contextmanager
def user_id_context(user_id: str | None) -> Iterator[None]:
    """Bind a user_id for the duration of a request. Restores prior on exit.

    Usage in server request handlers:

        with user_id_context(claims["sub"]):
            result = tools.get_state(project_id, ref, tier=tier)

    Implementation note: uses ``get()`` + ``set()`` rather than the
    typical ``.set()`` + ``.reset(token)`` pair because FastAPI runs a
    generator dependency's pre-yield and post-yield in different
    asyncio contexts (the route runs in a threadpool worker, the
    teardown in the event-loop task). ContextVar tokens are
    context-bound, so ``.reset(token)`` raises ValueError across that
    boundary. Manual save/restore is context-safe.
    """
    prev = _current_user_id.get()
    _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.set(prev)


def current_user_id() -> str | None:
    """Return the user id bound for the current request, or None."""
    return _current_user_id.get()
