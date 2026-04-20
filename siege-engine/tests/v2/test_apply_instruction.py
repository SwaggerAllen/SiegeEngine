"""Unit tests for the Phase 11 instruction → event dispatch.

One test class per instruction type. Each test sets up minimal
projection state, calls :func:`dispatch_instruction` directly, and
asserts the right event landed in ``graph_events`` plus the resulting
projection state. Route-layer concerns (HTTP, auth, queue row
lifecycle) live in ``test_queue_routes.py`` and ``test_queue.py``.
"""

from __future__ import annotations

import pytest

from backend.graph import apply_instruction as apply_mod
from backend.graph import events as ev
from backend.graph import instructions as instr
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.graph_event import GraphEvent
from backend.models.node import Edge, Node


def _make_node(
    db,
    project_id: str,
    *,
    tier: str = "comp",
    name: str = "X",
    kind: str = "domain",
    parent_id: str | None = None,
    content: str = "",
) -> str:
    """Create a node via ``append_event`` and return its id."""
    node_id = mint(db, Kind[tier.upper()])
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier=tier,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            parent_id=parent_id,
            name=name,
            content=content,
        ),
    )
    return node_id


def _event_types(db, project_id: str) -> list[str]:
    return [r.event_type for r in db.query(GraphEvent).filter_by(project_id=project_id).all()]


class TestCreate:
    def test_emits_node_created_and_inherits_parent_kind(self, db, project):
        parent_id = _make_node(db, project.id, tier="feat", name="Parent", kind="presentational")
        child_id = "resp_ABCDEFGH"
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.Create(node_id=child_id, tier="resp", name="Child", parent_id=parent_id),
        )
        node = db.get(Node, child_id)
        assert node is not None
        assert node.tier == "resp"
        assert node.parent_id == parent_id
        assert node.kind == "presentational"  # inherited
        assert "NodeCreated" in _event_types(db, project.id)

    def test_defaults_kind_to_domain_when_no_parent(self, db, project):
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.Create(node_id="feat_AAAAAAAA", tier="feat", name="Solo"),
        )
        node = db.get(Node, "feat_AAAAAAAA")
        assert node is not None and node.kind == "domain"


class TestDelete:
    def test_emits_node_deleted(self, db, project):
        nid = _make_node(db, project.id)
        apply_mod.dispatch_instruction(db, project.id, instr.Delete(node_id=nid, name="X"))
        assert "NodeDeleted" in _event_types(db, project.id)
        assert db.get(Node, nid) is None

    def test_raises_on_missing_node(self, db, project):
        with pytest.raises(apply_mod.InstructionApplyError):
            apply_mod.dispatch_instruction(
                db,
                project.id,
                instr.Delete(node_id="comp_DEADBEEF", name="Gone"),
            )


class TestRename:
    def test_enqueues_rename_rewrite_job(self, db, project):
        # PR #6 swaps the Rename dispatch to enqueue a
        # v2.rename_rewrite job rather than emit NodeRenamed
        # inline. The rewrite handler covers the renamed node's
        # own content + direct consumers before emitting the
        # canonical NodeRenamed event.
        from backend.graph.handlers.rename_rewrite import RENAME_REWRITE_JOB_TYPE
        from backend.models.job import Job

        nid = _make_node(db, project.id, name="Old")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.Rename(node_id=nid, old_name="Old", new_name="New"),
        )
        # Dispatch did NOT emit NodeRenamed inline; that lands once
        # the rewrite job runs.
        assert "NodeRenamed" not in _event_types(db, project.id)
        # And a rewrite job is queued with the payload.
        jobs = db.query(Job).filter_by(job_type=RENAME_REWRITE_JOB_TYPE).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {
            "project_id": project.id,
            "node_id": nid,
            "old_name": "Old",
            "new_name": "New",
        }


class TestReassignMapping:
    def test_emits_node_reparented(self, db, project):
        parent_a = _make_node(db, project.id, tier="feat", name="A")
        parent_b = _make_node(db, project.id, tier="feat", name="B")
        child = _make_node(db, project.id, tier="resp", parent_id=parent_a, name="Child")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.ReassignMapping(
                node_id=child,
                name="Child",
                new_parent_id=parent_b,
                new_parent_name="B",
            ),
        )
        node = db.get(Node, child)
        assert node is not None and node.parent_id == parent_b
        assert "NodeReparented" in _event_types(db, project.id)


class TestPromoteDemote:
    def test_promote_preserves_node_id(self, db, project):
        nid = _make_node(db, project.id, tier="resp", name="R")
        apply_mod.dispatch_instruction(
            db, project.id, instr.Promote(node_id=nid, name="R", new_tier="comp")
        )
        node = db.get(Node, nid)
        assert node is not None and node.id == nid and node.tier == "comp"

    def test_demote_with_reparent_emits_two_events(self, db, project):
        parent = _make_node(db, project.id, tier="comp", name="Top")
        nid = _make_node(db, project.id, tier="comp", name="X")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.Demote(
                node_id=nid,
                name="X",
                new_tier="impl",
                new_parent_id=parent,
                new_parent_name="Top",
            ),
        )
        types = _event_types(db, project.id)
        assert "NodeDemoted" in types and "NodeReparented" in types
        node = db.get(Node, nid)
        assert node is not None and node.tier == "impl" and node.parent_id == parent


class TestMergeSplit:
    def test_merge_emits_nodes_merged(self, db, project):
        # Merge collapses sources into dest; dest is typically one of the
        # sources so the surviving node carries forward with a new name.
        a = _make_node(db, project.id, name="A")
        b = _make_node(db, project.id, name="B")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.Merge(
                source_ids=[a, b],
                source_names=["A", "B"],
                dest_id=a,
                dest_name="AB",
            ),
        )
        assert "NodesMerged" in _event_types(db, project.id)
        # Dest survives with new name; other source is deleted.
        assert db.get(Node, a) is not None
        assert db.get(Node, b) is None

    def test_split_emits_node_split(self, db, project):
        src = _make_node(db, project.id, name="Src")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.Split(
                source_id=src,
                source_name="Src",
                dest_ids=["comp_YYYYYYYY", "comp_XXXXXXXX"],
                dest_names=["Y", "X"],
            ),
        )
        assert "NodeSplit" in _event_types(db, project.id)


class TestAddRemoveDependency:
    def test_add_dependency_emits_edge_created(self, db, project):
        a = _make_node(db, project.id, name="A")
        b = _make_node(db, project.id, name="B")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )
        edge = (
            db.query(Edge).filter_by(source_id=a, target_id=b, edge_type="dependency").one_or_none()
        )
        assert edge is not None

    def test_add_dependency_rejects_cycle(self, db, project):
        a = _make_node(db, project.id, name="A")
        b = _make_node(db, project.id, name="B")
        # Seed A→B; then try B→A which would close the cycle.
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )
        with pytest.raises(apply_mod.CycleDetected) as exc_info:
            apply_mod.dispatch_instruction(
                db,
                project.id,
                instr.AddDependency(source_id=b, source_name="B", target_id=a, target_name="A"),
            )
        assert a in exc_info.value.path and b in exc_info.value.path

    def test_duplicate_add_is_noop(self, db, project):
        a = _make_node(db, project.id, name="A")
        b = _make_node(db, project.id, name="B")
        ins = instr.AddDependency(source_id=a, source_name="A", target_id=b, target_name="B")
        apply_mod.dispatch_instruction(db, project.id, ins)
        apply_mod.dispatch_instruction(db, project.id, ins)  # second call no-ops
        edges = db.query(Edge).filter_by(source_id=a, target_id=b, edge_type="dependency").all()
        assert len(edges) == 1

    def test_remove_dependency_emits_edge_deleted(self, db, project):
        a = _make_node(db, project.id, name="A")
        b = _make_node(db, project.id, name="B")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.RemoveDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )
        edge = (
            db.query(Edge).filter_by(source_id=a, target_id=b, edge_type="dependency").one_or_none()
        )
        assert edge is None

    def test_remove_dependency_on_missing_edge_is_noop(self, db, project):
        a = _make_node(db, project.id, name="A")
        b = _make_node(db, project.id, name="B")
        # No edge exists; remove should silently succeed.
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.RemoveDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )  # does not raise


class TestAddRemoveDomainParent:
    def test_add_domain_parent_no_cycle_check(self, db, project):
        # Domain parent edges are presentational → domain; cycles are not
        # checked (different graph than dep edges).
        pres = _make_node(db, project.id, name="Pres", kind="presentational")
        dom = _make_node(db, project.id, name="Dom")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddDomainParent(
                source_id=pres, source_name="Pres", target_id=dom, target_name="Dom"
            ),
        )
        edge = (
            db.query(Edge)
            .filter_by(source_id=pres, target_id=dom, edge_type="domain_parent")
            .one_or_none()
        )
        assert edge is not None


class TestAddRemoveDecomposition:
    def test_add_decomposition_emits_edge(self, db, project):
        feat = _make_node(db, project.id, tier="feat", name="Billing")
        resp = _make_node(db, project.id, tier="resp", name="persist")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddDecomposition(
                source_id=feat,
                source_name="Billing",
                target_id=resp,
                target_name="persist",
            ),
        )
        edge = (
            db.query(Edge)
            .filter_by(source_id=feat, target_id=resp, edge_type="decomposition")
            .one_or_none()
        )
        assert edge is not None

    def test_remove_decomposition_emits_edge_deleted(self, db, project):
        feat = _make_node(db, project.id, tier="feat", name="Billing")
        resp = _make_node(db, project.id, tier="resp", name="persist")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddDecomposition(
                source_id=feat,
                source_name="Billing",
                target_id=resp,
                target_name="persist",
            ),
        )
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.RemoveDecomposition(
                source_id=feat,
                source_name="Billing",
                target_id=resp,
                target_name="persist",
            ),
        )
        edge = (
            db.query(Edge)
            .filter_by(source_id=feat, target_id=resp, edge_type="decomposition")
            .one_or_none()
        )
        assert edge is None


class TestPolicyApplication:
    def test_add_policy_application_emits_edge(self, db, project):
        policy = _make_node(db, project.id, tier="policy", name="Pol")
        comp = _make_node(db, project.id, name="C")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.AddPolicyApplication(
                policy_id=policy, policy_name="Pol", component_id=comp, component_name="C"
            ),
        )
        edge = (
            db.query(Edge)
            .filter_by(source_id=policy, target_id=comp, edge_type="policy_application")
            .one_or_none()
        )
        assert edge is not None

    def test_remove_policy_application_emits_edge_deleted(self, db, project):
        policy = _make_node(db, project.id, tier="policy", name="Pol")
        comp = _make_node(db, project.id, name="C")
        add = instr.AddPolicyApplication(
            policy_id=policy, policy_name="Pol", component_id=comp, component_name="C"
        )
        apply_mod.dispatch_instruction(db, project.id, add)
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.RemovePolicyApplication(
                policy_id=policy, policy_name="Pol", component_id=comp, component_name="C"
            ),
        )
        edge = (
            db.query(Edge)
            .filter_by(source_id=policy, target_id=comp, edge_type="policy_application")
            .one_or_none()
        )
        assert edge is None
