"""Tests for the phase-registry CLI subcommands + the plan-change
propagation pathway.

Covers:
- ``add-phase`` / ``remove-phase`` / ``assign-feature-to-phase`` /
  ``unassign-feature-from-phase`` — mechanical CRUD on
  ``state/phases/<id>.json`` files.
- ``mint-plan --dry-run`` — same projection + diff logic as the real
  mint, but no on-disk writes.
- ``compute_plan_change_worklist`` — the diff between the live plan
  projection and existing impl state files; emits pending entries for
  closure-changed impls and skipped entries for dropped-by-plan impls.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from siege.cli import main
from siege.propagation import compute_plan_change_worklist
from siege.state import DraftBlock, Scope, State


def _phase_dir(repo: Path) -> Path:
    return repo / "state" / "phases"


def _load_phase(repo: Path, phase_id: str) -> dict:
    return json.loads((_phase_dir(repo) / f"{phase_id}.json").read_text())


def test_add_phase_creates_state_file(tmp_path, capsys):
    capsys.readouterr()
    rc = main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "Phase 1",
            "--order",
            "1",
            "--phase-id",
            "phase_alpha",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["phase_id"] == "phase_alpha"
    payload = _load_phase(tmp_path, "phase_alpha")
    assert payload == {
        "schema_version": 2,
        "phase_id": "phase_alpha",
        "order": 1,
        "name": "Phase 1",
        "feature_ids": [],
    }


def test_add_phase_refuses_duplicate_id(tmp_path):
    main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A",
            "--order",
            "1",
            "--phase-id",
            "p1",
        ]
    )
    rc = main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A2",
            "--order",
            "2",
            "--phase-id",
            "p1",
        ]
    )
    assert rc == 2


def test_add_phase_refuses_duplicate_order(tmp_path):
    main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A",
            "--order",
            "1",
            "--phase-id",
            "p1",
        ]
    )
    rc = main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "B",
            "--order",
            "1",
            "--phase-id",
            "p2",
        ]
    )
    assert rc == 2


def test_remove_phase_refuses_when_features_attached(tmp_path):
    main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A",
            "--order",
            "1",
            "--phase-id",
            "p1",
        ]
    )
    main(
        [
            "assign-feature-to-phase",
            "--repo",
            str(tmp_path),
            "--feat-id",
            "feat_x",
            "--phase-id",
            "p1",
        ]
    )
    rc = main(["remove-phase", "--repo", str(tmp_path), "--phase-id", "p1"])
    assert rc == 2  # still owns feat_x


def test_remove_phase_deletes_when_empty(tmp_path):
    main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A",
            "--order",
            "1",
            "--phase-id",
            "p1",
        ]
    )
    rc = main(["remove-phase", "--repo", str(tmp_path), "--phase-id", "p1"])
    assert rc == 0
    assert not (_phase_dir(tmp_path) / "p1.json").exists()


def test_assign_feature_strips_from_prior_phase(tmp_path, capsys):
    """A feature lives in at most one phase. Reassigning moves it
    instead of duplicating it across phases."""
    for order, pid in ((1, "p1"), (2, "p2")):
        main(
            [
                "add-phase",
                "--repo",
                str(tmp_path),
                "--name",
                f"Phase {order}",
                "--order",
                str(order),
                "--phase-id",
                pid,
            ]
        )
    main(
        [
            "assign-feature-to-phase",
            "--repo",
            str(tmp_path),
            "--feat-id",
            "feat_x",
            "--phase-id",
            "p1",
        ]
    )
    capsys.readouterr()
    rc = main(
        [
            "assign-feature-to-phase",
            "--repo",
            str(tmp_path),
            "--feat-id",
            "feat_x",
            "--phase-id",
            "p2",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["moved_from"] == "p1"
    assert _load_phase(tmp_path, "p1")["feature_ids"] == []
    assert _load_phase(tmp_path, "p2")["feature_ids"] == ["feat_x"]


def test_unassign_feature_from_phase(tmp_path):
    main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A",
            "--order",
            "1",
            "--phase-id",
            "p1",
        ]
    )
    main(
        [
            "assign-feature-to-phase",
            "--repo",
            str(tmp_path),
            "--feat-id",
            "feat_y",
            "--phase-id",
            "p1",
        ]
    )
    rc = main(
        [
            "unassign-feature-from-phase",
            "--repo",
            str(tmp_path),
            "--feat-id",
            "feat_y",
            "--phase-id",
            "p1",
        ]
    )
    assert rc == 0
    assert _load_phase(tmp_path, "p1")["feature_ids"] == []


def test_unassign_feature_errors_when_absent(tmp_path):
    main(
        [
            "add-phase",
            "--repo",
            str(tmp_path),
            "--name",
            "A",
            "--order",
            "1",
            "--phase-id",
            "p1",
        ]
    )
    rc = main(
        [
            "unassign-feature-from-phase",
            "--repo",
            str(tmp_path),
            "--feat-id",
            "feat_nope",
            "--phase-id",
            "p1",
        ]
    )
    assert rc == 2


# ---------------- mint-plan --dry-run ----------------


def test_mint_plan_dry_run_does_not_write(tmp_path, capsys):
    """Dry-run emits the would-mint/would-reseed lists but leaves no
    state files behind. Real mint-plan against the same input does write."""
    plan = {
        "schema_version": 2,
        "phases": [
            {
                "order": 1,
                "impl_nodes": [
                    {
                        "parent_id": "comp_x",
                        "sub_id": "sub_a",
                        "phase": 1,
                        "closure_resp_ids": ["resp_1"],
                    }
                ],
            }
        ],
    }
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "plan.json").write_text(json.dumps(plan))
    capsys.readouterr()
    rc = main(["mint-plan", "--repo", str(tmp_path), "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["minted"] == ["state/impl/comp_x/p1/sub_a.json"]
    assert not (tmp_path / "state" / "impl").exists()

    # Real mint actually materializes the stub.
    rc = main(["mint-plan", "--repo", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "state" / "impl" / "comp_x" / "p1" / "sub_a.json").exists()


# ---------------- compute_plan_change_worklist ----------------


def _impl_state(parent: str, sub: str, phase: int, parent_resps: list[str]) -> State:
    scope = Scope(tier="impl", parent_id=parent, sub_id=sub, phase=phase)
    return State(
        schema_version=2,
        scope=scope,
        status="drafted",
        nonce="n",
        draft=DraftBlock(body_path=scope.body_path(), body_sha256="x", generated_at=""),
        meta={"parent_resps": parent_resps},
    )


class _FakeView:
    """Minimal view substitute exposing only what
    ``compute_plan_change_worklist`` reads.

    The real ``compute_plan`` is heavyweight (pulls the projection
    package); the test patches ``siege.projection.plan.compute_plan``
    so this view doesn't need to expose ``list_tier(other tiers)`` or
    the manifest plumbing."""

    def __init__(self, impl_states: list[State]):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self._impl = list(impl_states)

    def list_tier(self, tier: str) -> list[State]:
        return list(self._impl) if tier == "impl" else []


def test_plan_change_emits_closure_changed_impls(monkeypatch):
    """An impl whose plan-driven closure_resp_ids no longer matches its
    state's meta.parent_resps shows up as a pending entry."""
    view = _FakeView(
        [
            _impl_state("comp_x", "sub_a", 1, parent_resps=["resp_1"]),
            _impl_state("comp_x", "sub_b", 1, parent_resps=["resp_2"]),
        ]
    )
    plan = {
        "phases": [
            {
                "order": 1,
                "impl_nodes": [
                    # sub_a's closure expanded to two resps — closure changed.
                    {
                        "parent_id": "comp_x",
                        "sub_id": "sub_a",
                        "phase": 1,
                        "closure_resp_ids": ["resp_1", "resp_3"],
                    },
                    # sub_b matches its existing meta — no work needed.
                    {
                        "parent_id": "comp_x",
                        "sub_id": "sub_b",
                        "phase": 1,
                        "closure_resp_ids": ["resp_2"],
                    },
                ],
            }
        ]
    }
    monkeypatch.setattr("siege.projection.plan.compute_plan", lambda _v: plan)
    entries = compute_plan_change_worklist(view)  # type: ignore[arg-type]
    assert len(entries) == 1
    assert entries[0].scope.sub_id == "sub_a"
    assert entries[0].status == "pending"


def test_plan_change_skips_cold_start_impls(monkeypatch):
    """A plan node that has no existing impl state file is cold-start
    work — emitted by ``mint-plan``, not by the plan-change diff."""
    view = _FakeView([])
    plan = {
        "phases": [
            {
                "order": 1,
                "impl_nodes": [
                    {
                        "parent_id": "comp_x",
                        "sub_id": "sub_fresh",
                        "phase": 1,
                        "closure_resp_ids": ["resp_1"],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr("siege.projection.plan.compute_plan", lambda _v: plan)
    entries = compute_plan_change_worklist(view)  # type: ignore[arg-type]
    assert entries == []


def test_plan_change_emits_dropped_impls_as_skipped(monkeypatch):
    """An impl with a state file that the new plan no longer carries
    surfaces as a skipped entry with the 'dropped by plan' note."""
    view = _FakeView(
        [
            _impl_state("comp_x", "sub_dropped", 1, parent_resps=["resp_1"]),
        ]
    )
    plan: dict = {"phases": []}
    monkeypatch.setattr("siege.projection.plan.compute_plan", lambda _v: plan)
    entries = compute_plan_change_worklist(view)  # type: ignore[arg-type]
    assert len(entries) == 1
    assert entries[0].status == "skipped"
    assert entries[0].note == "dropped by plan"
    assert entries[0].scope.sub_id == "sub_dropped"


def test_plan_change_no_change_yields_empty(monkeypatch):
    """Steady state: every existing impl's closure matches its plan
    entry → empty worklist (no work needed)."""
    view = _FakeView([_impl_state("comp_x", "sub_a", 1, parent_resps=["resp_1"])])
    plan = {
        "phases": [
            {
                "order": 1,
                "impl_nodes": [
                    {
                        "parent_id": "comp_x",
                        "sub_id": "sub_a",
                        "phase": 1,
                        "closure_resp_ids": ["resp_1"],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr("siege.projection.plan.compute_plan", lambda _v: plan)
    entries = compute_plan_change_worklist(view)  # type: ignore[arg-type]
    assert entries == []


def test_plan_change_closure_order_independence(monkeypatch):
    """The closure comparison is order-independent — list reordering
    on either side must not appear as a change."""
    view = _FakeView([_impl_state("comp_x", "sub_a", 1, parent_resps=["resp_2", "resp_1"])])
    plan = {
        "phases": [
            {
                "order": 1,
                "impl_nodes": [
                    {
                        "parent_id": "comp_x",
                        "sub_id": "sub_a",
                        "phase": 1,
                        "closure_resp_ids": ["resp_1", "resp_2"],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr("siege.projection.plan.compute_plan", lambda _v: plan)
    assert compute_plan_change_worklist(view) == []  # type: ignore[arg-type]


# ---------------- CLI: open-propagation --from-plan-change ----------------


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    (path / "README").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def test_open_propagation_from_plan_change_rejects_mixed_flags(tmp_path):
    repo = _git_repo(tmp_path)
    with pytest.raises(SystemExit, match="mutually exclusive"):
        main(
            [
                "open-propagation",
                "--repo",
                str(repo),
                "--op-type",
                "plan_change",
                "--from-plan-change",
                "--worklist-json",
                json.dumps([{"scope": {"tier": "impl", "comp_id": "x"}}]),
            ]
        )


def test_open_propagation_from_plan_change_calls_compute(tmp_path, capsys, monkeypatch):
    """The CLI wires --from-plan-change to compute_plan_change_worklist —
    we patch the helper so we don't have to materialize a full plan +
    state tree, just verify the wiring."""
    repo = _git_repo(tmp_path)

    from siege.propagation import WorklistEntry

    sentinel_scope = Scope(tier="impl", parent_id="comp_x", sub_id="sub_a", phase=1)
    monkeypatch.setattr(
        "siege.propagation.compute_plan_change_worklist",
        lambda _v: [WorklistEntry(scope=sentinel_scope, status="pending")],
    )
    capsys.readouterr()
    rc = main(
        [
            "open-propagation",
            "--repo",
            str(repo),
            "--op-type",
            "plan_change",
            "--from-plan-change",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["pending"] == 1
    payload = json.loads(Path(out["state_path"]).read_text())
    assert payload["worklist"][0]["scope"]["sub_id"] == "sub_a"
    assert payload["op_type"] == "plan_change"
