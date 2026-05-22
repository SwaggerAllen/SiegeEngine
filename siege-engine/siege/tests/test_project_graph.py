"""Tests for build_project_graph — the whole-project graph projection.

build_project_graph takes a GitView and returns {ref, ref_head_sha,
nodes, edges}. Driven here with a lightweight fake view, the same
pattern test_plan.py uses: the projection is pure work over tier state
+ identity ledgers + one body read, so a fake that answers list_tier /
get_state / manifest_for_tier / get_manifest / read_body_text is enough.
"""

from __future__ import annotations

from siege.manifest import Manifest
from siege.projection.graph import build_project_graph
from siege.state import DraftBlock, ReviewBlock, Scope, State, Status


def _state(
    scope: Scope, status: Status = "approved", *, draft: bool = False, score: int | None = None
) -> State:
    return State(
        schema_version=1,
        scope=scope,
        status=status,
        nonce="n",
        draft=(
            DraftBlock(body_path=scope.body_path(), body_sha256="x", generated_at="")
            if draft
            else None
        ),
        review=(
            ReviewBlock(body_path=scope.review_path(), body_sha256="x", reviewed_at="", score=score)
            if score is not None
            else None
        ),
    )


def _manifest(substrate: Scope, nodes: list[dict]) -> Manifest:
    return Manifest(schema_version=2, substrate=substrate, derived_from_sha256="x", nodes=nodes)


class _FakeView:
    """The duck-typed surface build_project_graph reads."""

    def __init__(self, states, manifests, bodies):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self._states = {s.scope.key(): s for s in states}
        self._manifests = list(manifests)
        self._bodies = dict(bodies)

    def list_tier(self, tier):
        return [s for s in self._states.values() if s.scope.tier == tier]

    def get_state(self, scope):
        return self._states.get(scope.key())

    def manifest_for_tier(self, tier):
        return next((m for m in self._manifests if m.substrate.tier == tier), None)

    def get_manifest(self, scope):
        return next((m for m in self._manifests if m.substrate.key() == scope.key()), None)

    def read_body_text(self, path):
        return self._bodies[path]


_SYSARCH_BODY = """
<sysarch>
  <dependencies>
    <dep from="billing" to="auth"/>
  </dependencies>
  <domain-parent>
    <parent from="ui_billing" to="billing"/>
  </domain-parent>
</sysarch>
"""


def _sample_view() -> _FakeView:
    fe = Scope(tier="feature_expansion", comp_id="proj")
    req = Scope(tier="requirements", comp_id="proj")
    sysarch = Scope(tier="sysarch", comp_id="proj")
    states = [
        _state(fe, "approved"),
        _state(req, "approved"),
        _state(sysarch, "approved", draft=True),
        _state(Scope(tier="comparch", comp_id="comp_bil"), "drafted"),
        _state(
            Scope(tier="subcomparch", parent_id="comp_bil", sub_id="comp_s1"),
            "reviewed",
            score=70,
        ),
    ]
    manifests = [
        _manifest(
            fe,
            [
                {"id": "feat_a", "kind": "feature", "order": 0, "name": "Login", "implicit": False},
                {"id": "feat_b", "kind": "feature", "order": 1, "name": "Logout", "implicit": True},
            ],
        ),
        _manifest(
            req,
            [
                {
                    "id": "resp_x",
                    "kind": "responsibility",
                    "order": 0,
                    "name": "Auth",
                    "feats": ["feat_a", "feat_b"],
                },
            ],
        ),
        _manifest(
            sysarch,
            [
                {
                    "id": "comp_bil",
                    "kind": "component",
                    "order": 0,
                    "alias": "billing",
                    "name": "Billing",
                    "is_foundation": False,
                },
                {
                    "id": "comp_aut",
                    "kind": "component",
                    "order": 1,
                    "alias": "auth",
                    "name": "Auth",
                    "is_foundation": True,
                },
                {
                    "id": "comp_ui",
                    "kind": "component",
                    "order": 2,
                    "alias": "ui_billing",
                    "name": "BillingUI",
                    "is_foundation": False,
                },
            ],
        ),
        _manifest(
            Scope(tier="comparch", comp_id="comp_bil"),
            [
                {
                    "id": "comp_s1",
                    "kind": "subcomponent",
                    "order": 0,
                    "alias": "store",
                    "name": "BillingStore",
                    "is_foundation": False,
                },
            ],
        ),
    ]
    return _FakeView(states, manifests, {"sysarch/proj/body.md": _SYSARCH_BODY})


def _graph() -> dict:
    return build_project_graph(_sample_view())  # type: ignore[arg-type]


def test_nodes_span_all_tiers():
    by_id = {n["id"]: n for n in _graph()["nodes"]}
    assert set(by_id) == {
        "feat_a",
        "feat_b",
        "resp_x",
        "comp_bil",
        "comp_aut",
        "comp_ui",
        "comp_s1",
    }
    assert by_id["feat_a"]["kind"] == "feature"
    assert by_id["feat_a"]["tier"] == "feature_expansion"
    assert by_id["resp_x"]["kind"] == "responsibility"
    assert by_id["comp_bil"]["kind"] == "component"
    assert by_id["comp_s1"]["kind"] == "subcomponent"
    assert by_id["feat_b"]["implicit"] is True
    assert by_id["comp_aut"]["is_foundation"] is True
    assert by_id["feat_a"]["is_foundation"] is False


def test_subcomponent_parent_link():
    by_id = {n["id"]: n for n in _graph()["nodes"]}
    assert by_id["comp_s1"]["parent_id"] == "comp_bil"
    assert by_id["comp_bil"]["parent_id"] is None
    assert by_id["feat_a"]["parent_id"] is None


def test_node_lifecycle_from_own_substrate():
    """A component shows its comparch's status; a component with no
    comparch yet shows absent. A subcomponent shows its subcomparch."""
    by_id = {n["id"]: n for n in _graph()["nodes"]}
    assert by_id["comp_bil"]["status"] == "drafted"  # has a comparch state
    assert by_id["comp_aut"]["status"] == "absent"  # no comparch state
    assert by_id["comp_s1"]["status"] == "reviewed"
    assert by_id["comp_s1"]["score"] == 70
    # feature / responsibility nodes carry their declaring substrate's status
    assert by_id["feat_a"]["status"] == "approved"
    assert by_id["resp_x"]["status"] == "approved"


def test_decomposition_edges():
    edges = [e for e in _graph()["edges"] if e["type"] == "decomposition"]
    pairs = {(e["source_id"], e["target_id"]) for e in edges}
    assert pairs == {("feat_a", "resp_x"), ("feat_b", "resp_x")}


def test_dependency_and_domain_parent_edges():
    g = _graph()
    deps = {(e["source_id"], e["target_id"]) for e in g["edges"] if e["type"] == "dependency"}
    dps = {(e["source_id"], e["target_id"]) for e in g["edges"] if e["type"] == "domain_parent"}
    assert deps == {("comp_bil", "comp_aut")}
    assert dps == {("comp_ui", "comp_bil")}


def test_decomposition_edge_skips_unknown_feat():
    """A responsibility referencing a feat id that is not a known node
    drops the edge rather than emitting a dangling one."""
    view = _sample_view()
    for m in view._manifests:
        if m.substrate.tier == "requirements":
            m.nodes[0]["feats"].append("feat_ghost")
    g = build_project_graph(view)  # type: ignore[arg-type]
    sources = {e["source_id"] for e in g["edges"] if e["type"] == "decomposition"}
    assert "feat_ghost" not in sources


def test_empty_project():
    g = build_project_graph(_FakeView([], [], {}))  # type: ignore[arg-type]
    assert g["nodes"] == []
    assert g["edges"] == []
    assert g["ref"] == "main"
    assert g["ref_head_sha"] == "deadbeef"
