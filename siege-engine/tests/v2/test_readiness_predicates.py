"""Tests for backend.graph.handlers._readiness.

The four bespoke predicates wrap inline precondition checks that
today live inside individual generation handlers. The driver
(``run_tier_generation``) calls them via the ``readiness_check``
slot on ``TierGenerationConfig``. Phase A is purely additive —
these predicates exist alongside the in-handler checks until
Phase C migrates each tier to call them.
"""

from __future__ import annotations

from backend.graph import events as ev
from backend.graph.handlers._readiness import (
    all_of,
    owner_arch_approved,
    parent_comparch_approved,
    parent_subreqs_approved,
    subcomp_node_exists,
    sysarch_has_top_level_resps,
    sysarch_node_exists,
    top_level_comp_exists,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event


def _make_node(
    db,
    project_id,
    *,
    tier="comp",
    name="X",
    kind="domain",
    parent_id=None,
    content="",
):
    nid = mint(db, Kind[tier.upper()])
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier=tier,
            kind=kind,
            parent_id=parent_id,
            name=name,
            content=content,
        ),
    )
    return nid


class TestSysarchHasTopLevelResps:
    def test_passes_when_top_level_resp_exists(self, db, project):
        _make_node(db, project.id, tier="resp", name="R", parent_id=None)
        ready, reason = sysarch_has_top_level_resps(db, project.id, ())
        assert ready is True
        assert reason == ""

    def test_fails_when_no_resps(self, db, project):
        ready, reason = sysarch_has_top_level_resps(db, project.id, ())
        assert ready is False
        assert "no top-level responsibilities" in reason.lower()

    def test_subresps_alone_do_not_satisfy(self, db, project):
        # A resp with parent_id != None is a subresp — doesn't
        # count for the sysarch precondition.
        parent = _make_node(db, project.id, tier="comp", name="P")
        _make_node(db, project.id, tier="resp", name="Sub", parent_id=parent)
        ready, _ = sysarch_has_top_level_resps(db, project.id, ())
        assert ready is False


class TestParentSubreqsApproved:
    def test_passes_when_subreqs_has_content(self, db, project):
        comp_id = _make_node(db, project.id, tier="comp", name="Comp")
        # Subreqs is a subreqs-tier node parented to the comp.
        from backend.graph.subrequirements import bootstrap_subreqs_node

        subreqs_id = bootstrap_subreqs_node(db, project.id, comp_id)
        # Bootstrap creates an empty subreqs node. Set content to
        # simulate approval.
        from backend.models.node import Node

        node = db.get(Node, subreqs_id)
        assert node is not None
        node.content = "<subrequirements>...approved...</subrequirements>"
        db.flush()

        ready, reason = parent_subreqs_approved(db, project.id, (comp_id,))
        assert ready is True
        assert reason == ""

    def test_fails_when_subreqs_empty(self, db, project):
        comp_id = _make_node(db, project.id, tier="comp", name="Comp")
        from backend.graph.subrequirements import bootstrap_subreqs_node

        bootstrap_subreqs_node(db, project.id, comp_id)
        ready, reason = parent_subreqs_approved(db, project.id, (comp_id,))
        assert ready is False
        assert "subreqs_*" in reason or "subrequirements" in reason.lower()

    def test_fails_when_subreqs_missing(self, db, project):
        comp_id = _make_node(db, project.id, tier="comp", name="Comp")
        ready, reason = parent_subreqs_approved(db, project.id, (comp_id,))
        assert ready is False
        assert "blocked" in reason.lower()

    def test_fails_when_no_scope_id(self, db, project):
        ready, reason = parent_subreqs_approved(db, project.id, ())
        assert ready is False
        assert "missing component_id" in reason


class TestParentComparchApproved:
    def test_passes_when_parent_has_content(self, db, project):
        parent_id = _make_node(
            db,
            project.id,
            tier="comp",
            name="Parent",
            content="<comparch>approved</comparch>",
        )
        sub_id = _make_node(db, project.id, tier="comp", name="Sub", parent_id=parent_id)
        ready, reason = parent_comparch_approved(db, project.id, (sub_id,))
        assert ready is True
        assert reason == ""

    def test_fails_when_parent_content_empty(self, db, project):
        parent_id = _make_node(db, project.id, tier="comp", name="Parent")
        sub_id = _make_node(db, project.id, tier="comp", name="Sub", parent_id=parent_id)
        ready, reason = parent_comparch_approved(db, project.id, (sub_id,))
        assert ready is False
        assert "no approved comparch content" in reason

    def test_fails_when_node_missing(self, db, project):
        # The structural check (subcomp_node_exists) is now a
        # separate predicate. parent_comparch_approved assumes the
        # structural check has already passed; with a missing node
        # it returns the defensive "state invalid" message.
        ready, reason = parent_comparch_approved(db, project.id, ("comp_GHOST001",))
        assert ready is False

    def test_fails_when_top_level_comp(self, db, project):
        # parent_comparch_approved alone returns the defensive
        # "state invalid" path when called against a top-level
        # comp. The structural rejection lives on
        # subcomp_node_exists (covered in TestSubcompNodeExists).
        top_id = _make_node(db, project.id, tier="comp", name="Top")
        ready, _ = parent_comparch_approved(db, project.id, (top_id,))
        assert ready is False


class TestSysarchNodeExists:
    def test_passes_when_node_present(self, db, project):
        from backend.graph.sysarch import bootstrap_sysarch_node

        bootstrap_sysarch_node(db, project.id)
        ready, reason = sysarch_node_exists(db, project.id, ())
        assert ready is True
        assert reason == ""

    def test_fails_when_no_node(self, db, project):
        ready, reason = sysarch_node_exists(db, project.id, ())
        assert ready is False
        assert "no sysarch node" in reason.lower()


class TestTopLevelCompExists:
    def test_passes_for_top_level_comp(self, db, project):
        comp_id = _make_node(db, project.id, tier="comp", name="Top")
        ready, _ = top_level_comp_exists(db, project.id, (comp_id,))
        assert ready is True

    def test_fails_when_node_missing(self, db, project):
        ready, reason = top_level_comp_exists(db, project.id, ("comp_GONE0001",))
        assert ready is False
        assert "not found" in reason.lower()

    def test_fails_for_subcomp(self, db, project):
        parent_id = _make_node(db, project.id, tier="comp", name="P")
        sub_id = _make_node(db, project.id, tier="comp", name="Sub", parent_id=parent_id)
        ready, reason = top_level_comp_exists(db, project.id, (sub_id,))
        assert ready is False
        assert "subcomponent" in reason.lower()


class TestSubcompNodeExists:
    def test_passes_for_subcomp(self, db, project):
        parent_id = _make_node(db, project.id, tier="comp", name="P")
        sub_id = _make_node(db, project.id, tier="comp", name="Sub", parent_id=parent_id)
        ready, _ = subcomp_node_exists(db, project.id, (sub_id,))
        assert ready is True

    def test_fails_when_node_missing(self, db, project):
        ready, reason = subcomp_node_exists(db, project.id, ("comp_GONE0002",))
        assert ready is False
        assert "not found" in reason.lower()

    def test_fails_for_top_level_comp(self, db, project):
        top_id = _make_node(db, project.id, tier="comp", name="Top")
        ready, reason = subcomp_node_exists(db, project.id, (top_id,))
        assert ready is False
        assert "top-level component" in reason.lower()


class TestOwnerArchApproved:
    def test_passes_when_owner_has_content(self, db, project):
        owner_id = _make_node(
            db,
            project.id,
            tier="comp",
            name="Owner",
            content="<comparch>approved</comparch>",
        )
        ready, reason = owner_arch_approved(db, project.id, (owner_id,))
        assert ready is True
        assert reason == ""

    def test_fails_when_owner_content_empty(self, db, project):
        owner_id = _make_node(db, project.id, tier="comp", name="Owner")
        ready, reason = owner_arch_approved(db, project.id, (owner_id,))
        assert ready is False
        assert "has not yet been approved" in reason.lower()

    def test_fails_when_owner_wrong_tier(self, db, project):
        # Tier-check moved to owner_node_exists (covered in
        # TestOwnerNodeExists below); owner_arch_approved alone
        # returns the defensive "not found" / arch-not-approved
        # message when called on a non-comp node.
        wrong = _make_node(db, project.id, tier="resp", name="Resp")
        ready, _ = owner_arch_approved(db, project.id, (wrong,))
        assert ready is False

    def test_fails_when_owner_missing(self, db, project):
        ready, reason = owner_arch_approved(db, project.id, ("comp_NOPE0001",))
        assert ready is False
        assert "not found" in reason.lower()


class TestOwnerNodeExists:
    def test_passes_for_comp(self, db, project):
        from backend.graph.handlers._readiness import owner_node_exists

        comp_id = _make_node(db, project.id, tier="comp", name="C")
        ready, _ = owner_node_exists(db, project.id, (comp_id,))
        assert ready is True

    def test_fails_for_wrong_tier(self, db, project):
        from backend.graph.handlers._readiness import owner_node_exists

        wrong = _make_node(db, project.id, tier="resp", name="Resp")
        ready, reason = owner_node_exists(db, project.id, (wrong,))
        assert ready is False
        assert "not a comp_*" in reason

    def test_fails_when_missing(self, db, project):
        from backend.graph.handlers._readiness import owner_node_exists

        ready, reason = owner_node_exists(db, project.id, ("comp_GHOST002",))
        assert ready is False
        assert "not found" in reason.lower()


class TestAllOfCombinator:
    def test_returns_first_failure(self, db, project):
        def passes(_db, _pid, _scope):
            return (True, "")

        def fails(_db, _pid, _scope):
            return (False, "second predicate failed")

        def never_called(_db, _pid, _scope):
            raise AssertionError("short-circuit broken")

        combined = all_of(passes, fails, never_called)
        ready, reason = combined(db, project.id, ())
        assert ready is False
        assert reason == "second predicate failed"

    def test_returns_true_when_all_pass(self, db, project):
        def passes(_db, _pid, _scope):
            return (True, "")

        combined = all_of(passes, passes, passes)
        ready, reason = combined(db, project.id, ())
        assert ready is True
        assert reason == ""

    def test_empty_chain_passes(self, db, project):
        combined = all_of()
        ready, reason = combined(db, project.id, ())
        assert ready is True
        assert reason == ""
