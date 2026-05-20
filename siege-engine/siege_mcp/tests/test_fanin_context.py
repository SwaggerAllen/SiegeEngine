"""Tests for the phase-aware fan-in generation context.

``tiers.fanin.build_generation_context`` recomputes per phase:
fan-in-at-phase-N aggregates every impl node at phase ≤ N, and for a
subcomponent with several phased impl nodes keeps the highest-phase
one. An unphased (schema v1) fan-in reads every impl unchanged.

The builder only touches ``get_state`` / ``list_tier`` /
``read_body_text`` + ``ref`` / ``head_sha``, so a lightweight fake
view answering those is enough.
"""

from __future__ import annotations

from typing import Any

from siege_mcp.state import DraftBlock, Scope, State
from siege_mcp.tiers.fanin import build_generation_context


def _comp(comp_id: str) -> State:
    return State(
        schema_version=1,
        scope=Scope(tier="comparch", comp_id=comp_id),
        status="approved",
        nonce="n",
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


def _impl(parent_id: str, sub_id: str, phase: int | None) -> State:
    scope = Scope(tier="impl", parent_id=parent_id, sub_id=sub_id, phase=phase)
    return State(
        schema_version=2 if phase is not None else 1,
        scope=scope,
        status="approved",
        nonce="n",
        draft=DraftBlock(body_path=scope.body_path(), body_sha256="x", generated_at=""),
        meta={"name": sub_id},
    )


def _fanin(comp_id: str, phase: int | None) -> State:
    return State(
        schema_version=2 if phase is not None else 1,
        scope=Scope(tier="fanin", comp_id=comp_id, phase=phase),
        status="absent",
        nonce="n",
        meta={"owner_comp_id": comp_id},
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


def test_fanin_at_phase_2_includes_through_phase_2_excludes_later():
    """fan-in@2 aggregates the phase-1 and phase-2 impl nodes and
    excludes the phase-3 node — that work isn't built yet."""
    impl_a1 = _impl("comp_x", "sub_a", 1)
    impl_b2 = _impl("comp_x", "sub_b", 2)
    impl_c3 = _impl("comp_x", "sub_c", 3)
    view = _FakeView(
        states=[
            _comp("comp_x"),
            _sub("comp_x", "sub_a"),
            _sub("comp_x", "sub_b"),
            _sub("comp_x", "sub_c"),
            impl_a1,
            impl_b2,
            impl_c3,
            _fanin("comp_x", 2),
        ],
        bodies={
            impl_a1.draft.body_path: "SUB_A P1",  # type: ignore[union-attr]
            impl_b2.draft.body_path: "SUB_B P2",  # type: ignore[union-attr]
            impl_c3.draft.body_path: "SUB_C P3",  # type: ignore[union-attr]
        },
    )
    ctx = _build(view, Scope(tier="fanin", comp_id="comp_x", phase=2))
    assert ctx["scope"]["phase"] == 2
    subs = {b["sub_id"]: b for b in ctx["impl_bodies"]}
    assert set(subs) == {"sub_a", "sub_b"}
    assert subs["sub_a"]["body"] == "SUB_A P1"
    assert subs["sub_b"]["body"] == "SUB_B P2"


def test_fanin_dedups_a_sub_keeping_the_highest_phase():
    """A subcomponent with phase-1 and phase-2 impl nodes contributes
    exactly one body to fan-in@2 — the phase-2 one, which is
    delta-authored to cover the cumulative closure."""
    impl_a1 = _impl("comp_x", "sub_a", 1)
    impl_a2 = _impl("comp_x", "sub_a", 2)
    view = _FakeView(
        states=[
            _comp("comp_x"),
            _sub("comp_x", "sub_a"),
            impl_a1,
            impl_a2,
            _fanin("comp_x", 2),
        ],
        bodies={
            impl_a1.draft.body_path: "SUB_A P1",  # type: ignore[union-attr]
            impl_a2.draft.body_path: "SUB_A P2 CUMULATIVE",  # type: ignore[union-attr]
        },
    )
    ctx = _build(view, Scope(tier="fanin", comp_id="comp_x", phase=2))
    assert len(ctx["impl_bodies"]) == 1
    only = ctx["impl_bodies"][0]
    assert only["sub_id"] == "sub_a"
    assert only["phase"] == 2
    assert only["body"] == "SUB_A P2 CUMULATIVE"


def test_unphased_fanin_includes_every_impl():
    """A schema-v1 (unphased) fan-in scope reads every impl for the
    comp unchanged — no phase filter, no dedup."""
    impl_a = _impl("comp_x", "sub_a", None)
    impl_b = _impl("comp_x", "sub_b", None)
    view = _FakeView(
        states=[
            _comp("comp_x"),
            _sub("comp_x", "sub_a"),
            _sub("comp_x", "sub_b"),
            impl_a,
            impl_b,
            _fanin("comp_x", None),
        ],
        bodies={
            impl_a.draft.body_path: "SUB_A",  # type: ignore[union-attr]
            impl_b.draft.body_path: "SUB_B",  # type: ignore[union-attr]
        },
    )
    ctx = _build(view, Scope(tier="fanin", comp_id="comp_x"))
    assert ctx["scope"]["phase"] is None
    assert {b["sub_id"] for b in ctx["impl_bodies"]} == {"sub_a", "sub_b"}
