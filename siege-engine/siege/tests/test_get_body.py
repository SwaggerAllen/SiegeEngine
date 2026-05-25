"""Tests for tools.get_body — the substrate-body read endpoint that
the dashboard's V3 read panels call when source='upload'.

Builds a tiny fake GitView with just enough surface (get_state +
read_body_text + ref/head_sha) and monkeypatches siege.tools._open_view
to hand it back. Mirrors the pattern in test_project_graph.py.
"""

from __future__ import annotations

import siege.tools as tools
from siege.state import DraftBlock, Scope, State


class _FakeView:
    def __init__(self, state: State | None, bodies: dict[str, str]):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self._state = state
        self._bodies = bodies

    def get_state(self, scope: Scope) -> State | None:
        return self._state

    def read_body_text(self, path: str) -> str:
        if path not in self._bodies:
            raise FileNotFoundError(path)
        return self._bodies[path]


def _state_with_draft(scope: Scope, body_path: str) -> State:
    return State(
        schema_version=1,
        scope=scope,
        status="drafted",
        nonce="n",
        draft=DraftBlock(body_path=body_path, body_sha256="x", generated_at=""),
        review=None,
    )


def test_get_body_returns_text_when_draft_exists(monkeypatch):
    scope = Scope(tier="sysarch", comp_id="proj")
    body_path = "sysarch/proj/body.md"
    view = _FakeView(
        state=_state_with_draft(scope, body_path),
        bodies={body_path: "<components></components>"},
    )
    monkeypatch.setattr(tools, "_open_view", lambda *_, **__: view)

    out = tools.get_body("p1", "main", "sysarch", comp_id="proj")
    assert out["found"] is True
    assert out["body_path"] == body_path
    assert out["body_text"] == "<components></components>"
    assert out["ref"] == "main"
    assert out["ref_head_sha"] == "deadbeef"


def test_get_body_found_false_when_state_missing(monkeypatch):
    """No state for the scope → found=False, body_text="" — callers
    render an empty-state hint rather than 404-ing."""
    view = _FakeView(state=None, bodies={})
    monkeypatch.setattr(tools, "_open_view", lambda *_, **__: view)

    out = tools.get_body("p1", "main", "sysarch", comp_id="proj")
    assert out["found"] is False
    assert out["body_text"] == ""
    assert out["body_path"] is None


def test_get_body_found_false_when_state_has_no_draft(monkeypatch):
    """State exists but no draft block (e.g. an absent / approved-but-
    reset scope) → found=False. The path field is None — there's no
    draft.body_path to report."""
    scope = Scope(tier="sysarch", comp_id="proj")
    state = State(
        schema_version=1,
        scope=scope,
        status="absent",
        nonce="n",
        draft=None,
        review=None,
    )
    view = _FakeView(state=state, bodies={})
    monkeypatch.setattr(tools, "_open_view", lambda *_, **__: view)

    out = tools.get_body("p1", "main", "sysarch", comp_id="proj")
    assert out["found"] is False
    assert out["body_path"] is None


def test_get_body_found_false_when_body_file_missing(monkeypatch):
    """State + draft point at a body path that read_body_text can't
    read (file vanished, permission error, …) → found=False but the
    body_path is still surfaced so the UI can hint at what was
    expected."""
    scope = Scope(tier="sysarch", comp_id="proj")
    body_path = "sysarch/proj/body.md"
    view = _FakeView(
        state=_state_with_draft(scope, body_path),
        bodies={},  # the body file is "missing"
    )
    monkeypatch.setattr(tools, "_open_view", lambda *_, **__: view)

    out = tools.get_body("p1", "main", "sysarch", comp_id="proj")
    assert out["found"] is False
    assert out["body_path"] == body_path  # surfaced for the UI hint
    assert out["body_text"] == ""
