"""Tests for the upstream-chain context builders on the single-node model.

``feature_expansion`` and ``requirements`` are single-node arch tiers:
one substrate file each, declaring many nodes via a manifest. The
downstream readers — ``requirements`` / ``sysarch`` generation context
and ``_base.related_features_summary`` — pull node records from those
manifests rather than walking per-node state files.

The builders only touch a small duck-typed read surface, so a fake
view answering it is enough (same pattern as test_impl_context).
"""

from __future__ import annotations

from typing import Any

import pytest

from siege_mcp.manifest import Manifest, parse_manifest
from siege_mcp.state import Scope, State
from siege_mcp.tiers import _base, requirements, sysarch


def _feature_manifest() -> Manifest:
    return Manifest(
        schema_version=1,
        substrate=Scope(tier="feature_expansion", comp_id="proj"),
        derived_from_sha256="abc",
        nodes=[
            {
                "id": "feat_login",
                "kind": "feature",
                "order": 0,
                "name": "Login",
                "intent": "Users sign in.",
                "implicit": False,
            },
            {
                "id": "feat_admin",
                "kind": "feature",
                "order": 1,
                "name": "Admin Console",
                "intent": "Operators manage the system.",
                "implicit": True,
            },
        ],
    )


def _requirements_manifest() -> Manifest:
    return Manifest(
        schema_version=1,
        substrate=Scope(tier="requirements", comp_id="proj"),
        derived_from_sha256="def",
        nodes=[
            {
                "id": "resp_sess",
                "kind": "responsibility",
                "order": 0,
                "name": "session lifecycle",
                "feats": ["feat_login"],
            },
            {
                "id": "resp_perm",
                "kind": "responsibility",
                "order": 1,
                "name": "permission mapping",
                "feats": ["feat_admin", "feat_login"],
            },
            {
                "id": "resp_log",
                "kind": "responsibility",
                "order": 2,
                "name": "append-only event log",
                "feats": [],
            },
        ],
    )


class _FakeView:
    """Answers the read surface the upstream context builders touch."""

    def __init__(self, states: list[State], manifests: list[Manifest]):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self._by_key = {s.scope.key(): s for s in states}
        self._manifests: dict[str, Manifest] = {m.substrate.tier: m for m in manifests}
        self._nodes: dict[str, dict[str, Any]] = {}
        for m in manifests:
            for n in m.nodes:
                self._nodes[n["id"]] = n

    def get_state(self, scope: Scope) -> State | None:
        return self._by_key.get(scope.key())

    def list_tier(self, tier: str) -> list[State]:
        return [s for s in self._by_key.values() if s.scope.tier == tier]

    def manifest_for_tier(self, tier: str) -> Manifest | None:
        return self._manifests.get(tier)

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)


# ---------------- manifest parsing ----------------


def test_parse_manifest_round_trips_substrate_and_nodes():
    raw = {
        "schema_version": 1,
        "substrate": {"tier": "feature_expansion", "comp_id": "proj"},
        "derived_from_sha256": "abc",
        "nodes": [{"id": "feat_x", "kind": "feature", "name": "X"}],
    }
    m = parse_manifest(raw)
    assert m.substrate.tier == "feature_expansion"
    assert m.substrate.comp_id == "proj"
    assert m.derived_from_sha256 == "abc"
    node = m.node("feat_x")
    assert node is not None and node["name"] == "X"
    assert m.node("missing") is None


def test_parse_manifest_rejects_unknown_version():
    with pytest.raises(ValueError):
        parse_manifest(
            {
                "schema_version": 99,
                "substrate": {"tier": "requirements", "comp_id": "proj"},
                "nodes": [],
            }
        )


# ---------------- requirements generation context ----------------


def test_requirements_context_carries_feature_nodes():
    """The requirements generator gets every feature as a record with
    its stable feat_* ID — not the raw feature_expansion body."""
    scope = Scope(tier="requirements", comp_id="proj")
    view = _FakeView(states=[], manifests=[_feature_manifest()])
    ctx = requirements.build_generation_context(view, scope)  # type: ignore[arg-type]
    assert ctx["status"] == "absent"
    feats = {f["id"]: f for f in ctx["features"]}
    assert set(feats) == {"feat_login", "feat_admin"}
    assert feats["feat_login"]["intent"] == "Users sign in."
    assert feats["feat_admin"]["implicit"] is True
    # The raw feature_expansion body must not leak into the bundle.
    assert "feature" not in ctx
    assert "feature_expansion_body" not in ctx


def test_requirements_context_empty_when_no_manifest():
    """Before feature_expansion has drafted a manifest, the feature
    list is empty rather than a hard read failure."""
    scope = Scope(tier="requirements", comp_id="proj")
    view = _FakeView(states=[], manifests=[])
    ctx = requirements.build_generation_context(view, scope)  # type: ignore[arg-type]
    assert ctx["features"] == []


# ---------------- sysarch generation context ----------------


def test_sysarch_context_carries_features_and_responsibilities():
    scope = Scope(tier="sysarch", comp_id="proj")
    view = _FakeView(
        states=[],
        manifests=[_feature_manifest(), _requirements_manifest()],
    )
    ctx = sysarch.build_generation_context(view, scope)  # type: ignore[arg-type]
    assert {f["id"] for f in ctx["approved_features"]} == {"feat_login", "feat_admin"}
    resps = {r["id"]: r for r in ctx["approved_requirements"]}
    assert set(resps) == {"resp_sess", "resp_perm", "resp_log"}
    assert resps["resp_perm"]["feats"] == ["feat_admin", "feat_login"]
    assert resps["resp_log"]["feats"] == []
    # single-node sysarch — the multi-file sibling-section vestige is gone
    assert "sibling_sections" not in ctx
    assert "section_name" not in ctx


# ---------------- related-features walk ----------------


def test_related_features_summary_walks_resp_to_feat():
    """A comp owning resp_sess + resp_perm reaches feat_login (via
    both responsibilities) and feat_admin (via resp_perm) — deduped."""
    view = _FakeView(
        states=[],
        manifests=[_feature_manifest(), _requirements_manifest()],
    )
    comp = State(
        schema_version=1,
        scope=Scope(tier="comparch", comp_id="comp_a"),
        status="approved",
        nonce="n",
        meta={"parent_resps": ["resp_sess", "resp_perm"]},
    )
    summary = _base.related_features_summary(view, comp)  # type: ignore[arg-type]
    assert "**Login** (feat_login)" in summary
    assert "**Admin Console** (feat_admin)" in summary
    assert "Users sign in." in summary
    # feat_login is reached by both resps but listed exactly once.
    assert summary.count("feat_login") == 1


def test_related_features_summary_empty_without_parent_resps():
    view = _FakeView(
        states=[],
        manifests=[_feature_manifest(), _requirements_manifest()],
    )
    comp = State(
        schema_version=1,
        scope=Scope(tier="comparch", comp_id="comp_a"),
        status="approved",
        nonce="n",
        meta={},
    )
    assert _base.related_features_summary(view, comp) == ""  # type: ignore[arg-type]
