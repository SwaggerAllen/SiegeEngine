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
  <components>
    <component alias="billing">
      <name>Billing</name>
      <responsibilities>
        <resp id="resp_x"/>
      </responsibilities>
    </component>
    <component alias="ui_billing">
      <name>BillingUI</name>
      <responsibilities>
        <resp id="resp_x"/>
      </responsibilities>
    </component>
  </components>
  <policies>
    <policy>
      <name>Audit Every Privileged Action</name>
      <trigger>any privileged write</trigger>
      <required>resp_x</required>
      <rationale>writes must be auditable</rationale>
    </policy>
    <policy>
      <name>Encrypt Secrets at Rest</name>
      <trigger>any persisted secret</trigger>
      <rationale>secrets in the substrate must be encrypted</rationale>
    </policy>
  </policies>
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
        "sysarch_root",  # synthetic project-sysarch node
        "policy_audit-every-privileged-action",
        "policy_encrypt-secrets-at-rest",
    }
    assert by_id["sysarch_root"]["kind"] == "sysarch_root"
    assert by_id["sysarch_root"]["name"] == "Project Sysarch"
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
    """feat → resp decomposition edges projected from resp.feats. The
    set also carries resp → comp edges from the sysarch body's
    <responsibilities> blocks; those have their own test."""
    edges = [e for e in _graph()["edges"] if e["type"] == "decomposition"]
    pairs = {(e["source_id"], e["target_id"]) for e in edges}
    assert {("feat_a", "resp_x"), ("feat_b", "resp_x")}.issubset(pairs)


def test_dependency_and_domain_parent_edges():
    """Top-level dependency edges include the body-parsed comp→comp
    deps + the synthetic comp→sysarch_root edges (one per top-level
    comp). domain_parent stays body-parsed comp→comp only."""
    g = _graph()
    deps = {(e["source_id"], e["target_id"]) for e in g["edges"] if e["type"] == "dependency"}
    dps = {(e["source_id"], e["target_id"]) for e in g["edges"] if e["type"] == "domain_parent"}
    assert ("comp_bil", "comp_aut") in deps  # body-parsed comp→comp dep
    # synthetic root: every top-level comp emits a dep to it.
    assert ("comp_bil", "sysarch_root") in deps
    assert ("comp_aut", "sysarch_root") in deps
    assert ("comp_ui", "sysarch_root") in deps
    assert dps == {("comp_ui", "comp_bil")}


def test_synthetic_sysarch_root_lifecycle_mirrors_sysarch_state():
    """The synthetic root carries the sysarch substrate's status —
    'approved' in this fixture — so the dashboard treats it like a
    regular landed top-level node rather than 'absent'."""
    by_id = {n["id"]: n for n in _graph()["nodes"]}
    root = by_id["sysarch_root"]
    assert root["status"] == "approved"
    assert root["has_body"] is True


def test_resp_to_comp_decomposition_edges():
    """Every <component>'s <responsibilities><resp id="resp_X"/></responsibilities>
    block emits a decomposition resp_X → comp_id edge. A resp that
    appears in two component blocks (the domain + presentational mirror
    pattern) emits one edge per (resp, comp) pair, not duplicates."""
    g = _graph()
    decomp = {(e["source_id"], e["target_id"]) for e in g["edges"] if e["type"] == "decomposition"}
    # feat→resp edges from resp.feats are still there too.
    assert ("feat_a", "resp_x") in decomp
    # resp→comp edges from the sysarch body's per-component
    # <responsibilities> blocks — resp_x appears in both billing
    # (domain) and ui_billing (presentational mirror).
    assert ("resp_x", "comp_bil") in decomp
    assert ("resp_x", "comp_ui") in decomp


def test_resp_to_comp_edge_skips_unknown_resp():
    """A <resp id="..."/> ref that doesn't match a known responsibility
    node drops the edge rather than emitting a dangling one."""
    view = _sample_view()
    view._bodies["sysarch/proj/body.md"] = view._bodies["sysarch/proj/body.md"].replace(
        '<resp id="resp_x"/>', '<resp id="resp_x"/><resp id="resp_ghost"/>'
    )
    g = build_project_graph(view)  # type: ignore[arg-type]
    sources = {e["source_id"] for e in g["edges"] if e["type"] == "decomposition"}
    assert "resp_ghost" not in sources


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


def test_policy_nodes_have_slugged_ids_and_sysarch_lifecycle():
    """Each <policy> in the sysarch body becomes a kind='policy' node
    whose id is policy_<slug-of-name>. Lifecycle mirrors the sysarch
    substrate (approved here) — policies live and die with their body."""
    by_id = {n["id"]: n for n in _graph()["nodes"]}
    audit = by_id["policy_audit-every-privileged-action"]
    encrypt = by_id["policy_encrypt-secrets-at-rest"]
    assert audit["kind"] == "policy"
    assert audit["tier"] == "sysarch"
    assert audit["name"] == "Audit Every Privileged Action"
    assert audit["status"] == "approved"  # mirrors the sysarch state
    assert audit["parent_id"] is None
    assert encrypt["kind"] == "policy"


def test_every_top_level_comp_dep_edges_to_every_policy():
    """Policies are cross-cutting — every top-level component dep-edges
    to every policy, same pattern as the sysarch_root edge."""
    edges = _graph()["edges"]
    deps = {(e["source_id"], e["target_id"]) for e in edges if e["type"] == "dependency"}
    for comp in ("comp_bil", "comp_aut", "comp_ui"):
        assert (comp, "policy_audit-every-privileged-action") in deps
        assert (comp, "policy_encrypt-secrets-at-rest") in deps


def test_required_resp_decomposes_into_policy():
    """A <policy> with <required>resp_X</required> emits a
    decomposition edge resp_X → policy_<slug>. Policies without
    <required> get no decomposition edge."""
    edges = _graph()["edges"]
    decomp = {(e["source_id"], e["target_id"]) for e in edges if e["type"] == "decomposition"}
    assert ("resp_x", "policy_audit-every-privileged-action") in decomp
    # 'Encrypt Secrets at Rest' has no <required> — no resp → policy edge.
    assert not any(target == "policy_encrypt-secrets-at-rest" for (_, target) in decomp)


def test_unknown_required_resp_drops_decomposition_edge():
    """A <required>resp_ghost</required> that doesn't resolve drops
    the resp → policy decomposition edge rather than emitting a dangling
    one. The policy node itself is still emitted."""
    view = _sample_view()
    view._bodies["sysarch/proj/body.md"] = view._bodies["sysarch/proj/body.md"].replace(
        "<required>resp_x</required>", "<required>resp_ghost</required>"
    )
    g = build_project_graph(view)  # type: ignore[arg-type]
    ids = {n["id"] for n in g["nodes"]}
    assert "policy_audit-every-privileged-action" in ids  # node still emitted
    decomp_sources = {e["source_id"] for e in g["edges"] if e["type"] == "decomposition"}
    assert "resp_ghost" not in decomp_sources


def test_duplicate_policy_names_get_unique_ids():
    """Two policies named identically slug to the same base id; the
    second one gets a numeric suffix so both still appear in the graph."""
    view = _sample_view()
    body = view._bodies["sysarch/proj/body.md"]
    # Append a second policy with the same name as the first.
    extra = (
        "  <policy>"
        "<name>Audit Every Privileged Action</name>"
        "<trigger>different trigger</trigger>"
        "<rationale>different rationale</rationale>"
        "</policy>"
    )
    view._bodies["sysarch/proj/body.md"] = body.replace("</policies>", f"{extra}</policies>")
    g = build_project_graph(view)  # type: ignore[arg-type]
    ids = {n["id"] for n in g["nodes"]}
    assert "policy_audit-every-privileged-action" in ids
    assert "policy_audit-every-privileged-action_2" in ids


def test_empty_policies_block_emits_no_policy_nodes():
    """An empty <policies></policies> emits zero policy nodes — and
    therefore zero comp → policy edges. Sysarch_root + comp → root
    edges keep working."""
    view = _sample_view()
    body = view._bodies["sysarch/proj/body.md"]
    # Strip the whole <policies>…</policies> block.
    import re

    view._bodies["sysarch/proj/body.md"] = re.sub(
        r"<policies>.*?</policies>", "<policies></policies>", body, flags=re.S
    )
    g = build_project_graph(view)  # type: ignore[arg-type]
    policy_ids = [n["id"] for n in g["nodes"] if n["kind"] == "policy"]
    assert policy_ids == []
    # sysarch_root still attached.
    deps = {(e["source_id"], e["target_id"]) for e in g["edges"] if e["type"] == "dependency"}
    assert ("comp_bil", "sysarch_root") in deps
