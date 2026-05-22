"""Tests for the phase-aware impl generation context.

``tiers.impl.build_generation_context`` threads two phase-only keys
into the bundle: ``prior_phase_impl_body`` (the same subcomponent's
impl artifact from the nearest earlier phase) and
``dep_fanin_summaries`` (the prior-phase fan-in synthesis of each
dependency component). These tests drive the builder with a
lightweight fake view — the builder only touches the read surface
``get_state`` / ``list_tier`` / ``read_body_text`` + ``ref`` /
``head_sha``, so a fake that answers those is enough.
"""

from __future__ import annotations

from typing import Any

from siege.projection.impl import build_generation_context
from siege.state import DraftBlock, Scope, State


def _comp(comp_id: str, deps: list[str] | None = None) -> State:
    return State(
        schema_version=1,
        scope=Scope(tier="comparch", comp_id=comp_id),
        status="approved",
        nonce="n",
        edges={"dependencies": deps or []},
        meta={"name": comp_id},
    )


def _sub(parent_id: str, sub_id: str) -> State:
    return State(
        schema_version=1,
        scope=Scope(tier="subcomparch", parent_id=parent_id, sub_id=sub_id),
        status="approved",
        nonce="n",
        meta={"name": sub_id},
    )


def _impl(parent_id: str, sub_id: str, phase: int) -> State:
    scope = Scope(tier="impl", parent_id=parent_id, sub_id=sub_id, phase=phase)
    return State(
        schema_version=2,
        scope=scope,
        status="approved",
        nonce="n",
        draft=DraftBlock(body_path=scope.body_path(), body_sha256="x", generated_at=""),
        meta={"parent_resps": []},
    )


def _fanin(comp_id: str, phase: int) -> State:
    scope = Scope(tier="fanin", comp_id=comp_id, phase=phase)
    return State(
        schema_version=2,
        scope=scope,
        status="approved",
        nonce="n",
        draft=DraftBlock(body_path=scope.body_path(), body_sha256="x", generated_at=""),
    )


class _FakeView:
    """Answers the read surface ``build_generation_context`` touches."""

    def __init__(self, states: list[State], bodies: dict[str, str]):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self._by_key = {s.scope.key(): s for s in states}
        self._bodies = bodies

    def get_state(self, scope: Scope) -> State | None:
        return self._by_key.get(scope.key())

    def list_tier(self, tier: str) -> list[State]:
        return [s for s in self._by_key.values() if s.scope.tier == tier]

    def read_body_text(self, path: str) -> str:
        return self._bodies[path]


def _build(view: "_FakeView", scope: Scope) -> dict[str, Any]:
    """build_generation_context only uses the duck-typed surface
    _FakeView provides; the ignore is the single concession to that."""
    return build_generation_context(view, scope)  # type: ignore[arg-type]


def test_phase2_bundle_carries_prior_impl_and_dep_fanin():
    """A phase-2 impl node sees its own phase-1 impl body as prior and
    the phase-1 fan-in synthesis of its parent comp's dependency."""
    impl_p1 = _impl("comp_x", "sub_x", 1)
    impl_p2 = _impl("comp_x", "sub_x", 2)
    fanin_p1 = _fanin("comp_dep", 1)
    view = _FakeView(
        states=[
            _comp("comp_x", deps=["comp_dep"]),
            _comp("comp_dep"),
            _sub("comp_x", "sub_x"),
            impl_p1,
            impl_p2,
            fanin_p1,
        ],
        bodies={
            impl_p1.draft.body_path: "PHASE 1 IMPL BODY",  # type: ignore[union-attr]
            fanin_p1.draft.body_path: "DEP FANIN SYNTHESIS P1",  # type: ignore[union-attr]
        },
    )
    ctx = _build(view, impl_p2.scope)
    assert ctx["scope"]["phase"] == 2
    assert ctx["prior_phase_impl_body"] == "PHASE 1 IMPL BODY"
    assert len(ctx["dep_fanin_summaries"]) == 1
    dep = ctx["dep_fanin_summaries"][0]
    assert dep["comp_id"] == "comp_dep"
    assert dep["phase"] == 1
    assert dep["synthesis"] == "DEP FANIN SYNTHESIS P1"


def test_first_phase_bundle_has_empty_prior():
    """The earliest phase has no prior impl body and — with no
    dependency fan-in below it — no dep fan-in summaries."""
    impl_p1 = _impl("comp_x", "sub_x", 1)
    view = _FakeView(
        states=[_comp("comp_x"), _sub("comp_x", "sub_x"), impl_p1],
        bodies={impl_p1.draft.body_path: "PHASE 1 IMPL BODY"},  # type: ignore[union-attr]
    )
    ctx = _build(view, impl_p1.scope)
    assert ctx["scope"]["phase"] == 1
    assert ctx["prior_phase_impl_body"] == ""
    assert ctx["dep_fanin_summaries"] == []


def test_prior_impl_is_nearest_earlier_phase():
    """With phases 1 and 3 minted (no 2), the phase-3 node's prior is
    phase 1 — the largest phase strictly below, not blindly phase-1."""
    impl_p1 = _impl("comp_x", "sub_x", 1)
    impl_p3 = _impl("comp_x", "sub_x", 3)
    view = _FakeView(
        states=[_comp("comp_x"), _sub("comp_x", "sub_x"), impl_p1, impl_p3],
        bodies={impl_p1.draft.body_path: "PHASE 1 IMPL BODY"},  # type: ignore[union-attr]
    )
    ctx = _build(view, impl_p3.scope)
    assert ctx["prior_phase_impl_body"] == "PHASE 1 IMPL BODY"


def test_dep_fanin_excludes_current_and_later_phases():
    """A phase-2 node's dep fan-in is the nearest synthesis strictly
    below phase 2 — the dependency's phase-2 fan-in is not yet
    available when this node builds."""
    impl_p2 = _impl("comp_x", "sub_x", 2)
    fanin_p1 = _fanin("comp_dep", 1)
    fanin_p2 = _fanin("comp_dep", 2)
    view = _FakeView(
        states=[
            _comp("comp_x", deps=["comp_dep"]),
            _comp("comp_dep"),
            _sub("comp_x", "sub_x"),
            impl_p2,
            fanin_p1,
            fanin_p2,
        ],
        bodies={
            fanin_p1.draft.body_path: "DEP FANIN P1",  # type: ignore[union-attr]
            fanin_p2.draft.body_path: "DEP FANIN P2",  # type: ignore[union-attr]
        },
    )
    ctx = _build(view, impl_p2.scope)
    assert len(ctx["dep_fanin_summaries"]) == 1
    assert ctx["dep_fanin_summaries"][0]["phase"] == 1
    assert ctx["dep_fanin_summaries"][0]["synthesis"] == "DEP FANIN P1"
