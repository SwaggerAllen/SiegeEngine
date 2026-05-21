"""Tests for the compute_plan phasing projection.

compute_plan takes a GitView and returns the plan dict. These tests
drive it with a lightweight fake view — a fixture git repo would be
more faithful but the algorithm is pure graph work over tier state,
so a fake that answers list_tier + the registry tree-read is enough.
"""

from __future__ import annotations

import json

from siege_mcp.plan import compute_plan
from siege_mcp.state import Scope, State


def _comp(comp_id, parent_resps, deps=None, name=None):
    return State(
        schema_version=1,
        scope=Scope(tier="comparch", comp_id=comp_id),
        status="approved",
        nonce="n",
        edges={"dependencies": deps or []},
        meta={"parent_resps": parent_resps, "name": name or comp_id},
    )


def _sub(parent_id, sub_id, parent_resps):
    return State(
        schema_version=1,
        scope=Scope(tier="subcomparch", parent_id=parent_id, sub_id=sub_id),
        status="approved",
        nonce="n",
        meta={"parent_resps": parent_resps},
    )


def _req(resp_id, feature_id):
    return State(
        schema_version=1,
        scope=Scope(tier="requirements", comp_id=resp_id),
        status="approved",
        nonce="n",
        meta={"feature_id": feature_id},
    )


def _feat(feat_id):
    return State(
        schema_version=1,
        scope=Scope(tier="feature_expansion", comp_id=feat_id),
        status="approved",
        nonce="n",
    )


class _FakeClone:
    """Answers the direct tree-read compute_plan does for the registry."""

    def __init__(self, registry_files: dict[str, dict]):
        self._registry = registry_files

    def ls_tree(self, _sha, prefix):
        if prefix == "state/phases/":
            return list(self._registry.keys())
        return []

    def show_blob(self, _sha, path):
        return json.dumps(self._registry[path]).encode("utf-8")


class _FakeView:
    def __init__(self, registry_files, states_by_tier):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self.clone = _FakeClone(registry_files)
        self._by_tier = states_by_tier

    def list_tier(self, tier):
        return self._by_tier.get(tier, [])


def _plan(view: "_FakeView") -> dict:
    """compute_plan only uses the duck-typed surface _FakeView provides
    (ref, head_sha, clone.ls_tree/show_blob, list_tier). The ignore is
    the single concession to that — kept in one place."""
    return compute_plan(view)  # type: ignore[arg-type]


def _registry(*phases):
    """phases: (order, phase_id, name, [feature_ids])."""
    return {
        f"state/phases/{pid}.json": {
            "schema_version": 2,
            "phase_id": pid,
            "name": name,
            "order": order,
            "feature_ids": feats,
        }
        for order, pid, name, feats in phases
    }


def test_basic_three_phase_plan():
    """One subcomp per comp, one feature per phase. No rearrangement."""
    view = _FakeView(
        _registry(
            (1, "p1", "Foundation", ["feat_a"]),
            (2, "p2", "Beta", ["feat_b"]),
            (3, "p3", "GA", ["feat_c"]),
        ),
        {
            "comparch": [
                _comp("comp_x", ["resp_a"]),
                _comp("comp_y", ["resp_b"]),
                _comp("comp_z", ["resp_c"]),
            ],
            "subcomparch": [
                _sub("comp_x", "sub_x", ["resp_a"]),
                _sub("comp_y", "sub_y", ["resp_b"]),
                _sub("comp_z", "sub_z", ["resp_c"]),
            ],
            "requirements": [
                _req("resp_a", "feat_a"),
                _req("resp_b", "feat_b"),
                _req("resp_c", "feat_c"),
            ],
            "feature_expansion": [_feat("feat_a"), _feat("feat_b"), _feat("feat_c")],
            "impl": [],
        },
    )
    plan = _plan(view)
    assert plan["errors"] == []
    assert plan["rearrangements"] == []
    assert plan["aggregates"]["impl_node_count"] == 3
    by_order = {p["order"]: p for p in plan["phases"]}
    assert [n["sub_id"] for n in by_order[1]["impl_nodes"]] == ["sub_x"]
    assert [n["sub_id"] for n in by_order[2]["impl_nodes"]] == ["sub_y"]
    assert [n["sub_id"] for n in by_order[3]["impl_nodes"]] == ["sub_z"]


def test_dependency_pulls_a_component_earlier():
    """comp_z is assigned phase 3 (serves feat_c) but comp_y (phase 2)
    depends on it → effective-phase fixpoint pulls comp_z to phase 2,
    recorded as a rearrangement."""
    view = _FakeView(
        _registry(
            (1, "p1", "Foundation", ["feat_a"]),
            (2, "p2", "Beta", ["feat_b"]),
            (3, "p3", "GA", ["feat_c"]),
        ),
        {
            "comparch": [
                _comp("comp_x", ["resp_a"]),
                _comp("comp_y", ["resp_b"], deps=["comp_z"]),
                _comp("comp_z", ["resp_c"]),
            ],
            "subcomparch": [
                _sub("comp_x", "sub_x", ["resp_a"]),
                _sub("comp_y", "sub_y", ["resp_b"]),
                _sub("comp_z", "sub_z", ["resp_c"]),
            ],
            "requirements": [
                _req("resp_a", "feat_a"),
                _req("resp_b", "feat_b"),
                _req("resp_c", "feat_c"),
            ],
            "feature_expansion": [_feat("feat_a"), _feat("feat_b"), _feat("feat_c")],
            "impl": [],
        },
    )
    plan = _plan(view)
    assert plan["errors"] == []
    assert len(plan["rearrangements"]) == 1
    r = plan["rearrangements"][0]
    assert r["comp_id"] == "comp_z"
    assert r["requested_phase"] == 3
    assert r["scheduled_phase"] == 2
    assert r["required_by"] == "comp_y"
    # comp_z's sub_z impl node now lands in phase 2, not 3.
    by_order = {p["order"]: p for p in plan["phases"]}
    assert "sub_z" in [n["sub_id"] for n in by_order[2]["impl_nodes"]]
    assert by_order[3]["impl_nodes"] == []


def test_subcomp_serving_two_phases_gets_two_impl_nodes():
    """sub_x owns resp_a (feat_a, phase 1) AND resp_c (feat_c, phase 3)
    → two impl nodes, p1 and p3. The p3 closure is cumulative."""
    view = _FakeView(
        _registry(
            (1, "p1", "Foundation", ["feat_a"]),
            (3, "p3", "GA", ["feat_c"]),
        ),
        {
            "comparch": [_comp("comp_x", ["resp_a", "resp_c"])],
            "subcomparch": [_sub("comp_x", "sub_x", ["resp_a", "resp_c"])],
            "requirements": [_req("resp_a", "feat_a"), _req("resp_c", "feat_c")],
            "feature_expansion": [_feat("feat_a"), _feat("feat_c")],
            "impl": [],
        },
    )
    plan = _plan(view)
    assert plan["errors"] == []
    nodes = [n for ph in plan["phases"] for n in ph["impl_nodes"]]
    assert len(nodes) == 2
    p1 = next(n for n in nodes if n["phase"] == 1)
    p3 = next(n for n in nodes if n["phase"] == 3)
    # p1 closure has only the phase-1 resp; p3 is cumulative.
    assert p1["closure_resp_ids"] == ["resp_a"]
    assert p3["closure_resp_ids"] == ["resp_a", "resp_c"]


def test_unassigned_feature_is_a_hard_error():
    view = _FakeView(
        _registry((1, "p1", "Foundation", ["feat_a"])),
        {
            "comparch": [_comp("comp_x", ["resp_a"])],
            "subcomparch": [_sub("comp_x", "sub_x", ["resp_a"])],
            "requirements": [_req("resp_a", "feat_a")],
            # feat_b exists but is in no phase registry file.
            "feature_expansion": [_feat("feat_a"), _feat("feat_b")],
            "impl": [],
        },
    )
    plan = _plan(view)
    assert any("feat_b" in e for e in plan["errors"])
    assert plan["aggregates"]["error_count"] >= 1


def test_build_order_respects_dependency_topology():
    """Within a phase, a dependency comp's node precedes its dependent's."""
    view = _FakeView(
        _registry((1, "p1", "Foundation", ["feat_a", "feat_b"])),
        {
            "comparch": [
                _comp("comp_a", ["resp_a"], deps=["comp_b"]),
                _comp("comp_b", ["resp_b"]),
            ],
            "subcomparch": [
                _sub("comp_a", "sub_a", ["resp_a"]),
                _sub("comp_b", "sub_b", ["resp_b"]),
            ],
            "requirements": [_req("resp_a", "feat_a"), _req("resp_b", "feat_b")],
            "feature_expansion": [_feat("feat_a"), _feat("feat_b")],
            "impl": [],
        },
    )
    plan = _plan(view)
    order = [n["sub_id"] for n in plan["phases"][0]["build_order"]]
    # comp_a depends on comp_b → sub_b builds before sub_a.
    assert order.index("sub_b") < order.index("sub_a")
