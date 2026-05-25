"""Tests for siege.propagation — the worklist primitive `/regen_below`
opens and `/status` reads to surface in-flight iteration loops.

Covers schema round-trip, the rolled-up-status logic, the mutation
helpers (update_entry / add_entries), and the CLI write-then-read
path that materializes records under state/propagations/.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from siege.cli import main
from siege.propagation import (
    PROPAGATION_SCHEMA_VERSION,
    WorklistEntry,
    add_entries,
    dump_propagation,
    load_propagation,
    new_propagation,
    read_propagation,
    update_entry,
    write_propagation,
)
from siege.state import Scope, Tier


def _entry(tier: Tier, comp_id: str, status: str = "pending") -> WorklistEntry:
    return WorklistEntry(scope=Scope(tier=tier, comp_id=comp_id), status=status)


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    (path / "README").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


# ---------------- Schema + status roll-up ----------------


def test_rolled_up_status_is_open_until_every_entry_terminal():
    """An open record rolls up to ``open`` while any entry is still
    pending or in_progress. ``complete`` requires every entry to be
    in a terminal state (done or skipped)."""
    prop = new_propagation(
        op_type="regen_downstream",
        worklist=[_entry("comparch", "comp_a"), _entry("comparch", "comp_b")],
    )
    assert prop.status == "open"
    prop = update_entry(prop, Scope(tier="comparch", comp_id="comp_a"), status="done")
    assert prop.status == "open"
    prop = update_entry(prop, Scope(tier="comparch", comp_id="comp_b"), status="skipped")
    assert prop.status == "complete"


def test_empty_worklist_rolls_up_complete():
    """Degenerate but harmless — a record opened over zero scopes is
    immediately ``complete``. The caller usually skips writing one in
    that case, but the roll-up is well-defined."""
    prop = new_propagation(op_type="regen_downstream", worklist=[])
    assert prop.status == "complete"
    assert prop.counts == {"pending": 0, "in_progress": 0, "done": 0, "skipped": 0}


def test_counts_break_down_by_status():
    prop = new_propagation(
        op_type="regen_below_threshold",
        worklist=[
            _entry("comparch", "comp_a", "done"),
            _entry("comparch", "comp_b", "in_progress"),
            _entry("comparch", "comp_c", "pending"),
            _entry("comparch", "comp_d", "skipped"),
        ],
    )
    assert prop.counts == {"pending": 1, "in_progress": 1, "done": 1, "skipped": 1}


# ---------------- Mutation helpers ----------------


def test_update_entry_returns_new_record_with_flipped_status():
    """update_entry is pure — the original record is unchanged so
    accidental sharing doesn't corrupt state during a multi-step
    update sequence."""
    prop = new_propagation(
        op_type="regen_downstream",
        worklist=[_entry("comparch", "comp_a"), _entry("comparch", "comp_b")],
    )
    updated = update_entry(prop, Scope(tier="comparch", comp_id="comp_a"), status="done", note="ok")
    assert prop.worklist[0].status == "pending"  # original untouched
    assert updated.worklist[0].status == "done"
    assert updated.worklist[0].note == "ok"


def test_update_entry_raises_on_missing_scope():
    """A flip targeting a scope that isn't in the worklist is a
    stale-worklist signal — surface it loudly rather than silently
    appending an entry the record never opened."""
    prop = new_propagation(op_type="regen_downstream", worklist=[_entry("comparch", "comp_a")])
    with pytest.raises(KeyError):
        update_entry(prop, Scope(tier="comparch", comp_id="ghost"), status="done")


def test_add_entries_appends_only_new_scopes():
    """The "extend on mid-drain upstream change" path: re-running the
    compute helper on a partially-drained record should append only
    the not-yet-tracked scopes, leave the drained ones alone."""
    prop = new_propagation(
        op_type="regen_downstream", worklist=[_entry("comparch", "comp_a", "done")]
    )
    extended = add_entries(
        prop,
        [
            _entry("comparch", "comp_a"),  # already there — skip
            _entry("comparch", "comp_b"),  # new — append
        ],
    )
    assert [e.scope.comp_id for e in extended.worklist] == ["comp_a", "comp_b"]
    # The already-drained entry keeps its done status.
    assert extended.worklist[0].status == "done"


def test_add_entries_no_change_when_all_present_is_identity():
    """No new entries → return the same record (identity short-circuit)."""
    prop = new_propagation(op_type="regen_downstream", worklist=[_entry("comparch", "comp_a")])
    assert add_entries(prop, [_entry("comparch", "comp_a")]) is prop


# ---------------- JSON round-trip ----------------


def test_dump_and_load_round_trip(tmp_path: Path):
    """A propagation written + read back via the on-disk format is
    structurally identical to the original (modulo dict ordering)."""
    prop = new_propagation(
        op_type="regen_downstream",
        worklist=[_entry("comparch", "comp_a"), _entry("subcomparch", "sub_1")],
        tier="comparch",
        threshold=72,
        source_scope=Scope(tier="sysarch", comp_id="proj"),
        meta={"batch_id": "batch_xyz"},
    )
    path = write_propagation(tmp_path, prop)
    assert path == tmp_path / "state" / "propagations" / f"{prop.propagation_id}.json"
    rehydrated = read_propagation(tmp_path, prop.propagation_id)
    assert rehydrated == prop


def test_dump_includes_rolled_up_status_and_counts():
    """Serialized propagation carries ``status`` + ``counts`` so the
    dashboard / list endpoint can filter without rehydrating the
    dataclass on every record."""
    prop = new_propagation(
        op_type="regen_downstream",
        worklist=[_entry("comparch", "comp_a", "done")],
    )
    payload = dump_propagation(prop)
    assert payload["status"] == "complete"
    assert payload["counts"]["done"] == 1
    assert payload["schema_version"] == PROPAGATION_SCHEMA_VERSION


def test_load_tolerates_missing_optional_fields():
    """Pre-meta and no-source-scope records still parse."""
    minimal: dict = {
        "schema_version": 1,
        "propagation_id": "prop_X",
        "started_at": "2026-05-25T00:00:00Z",
        "op_type": "regen_downstream",
        "worklist": [],
    }
    prop = load_propagation(minimal)
    assert prop.meta == {}
    assert prop.source_scope is None
    assert prop.threshold is None


# ---------------- CLI integration ----------------


def test_cli_open_then_update_then_list(tmp_path: Path, capsys):
    """The skill chain calls ``open-propagation`` once, then
    ``update-propagation-entry`` once per scope. ``list-propagations``
    is what ``/status`` reads. Exercise the three together against a
    real on-disk repo so the file layout + reader path are pinned."""
    repo = _git_repo(tmp_path)
    worklist = [
        {"scope": {"tier": "comparch", "comp_id": "comp_a"}},
        {"scope": {"tier": "comparch", "comp_id": "comp_b"}},
    ]
    rc = main(
        [
            "open-propagation",
            "--repo",
            str(repo),
            "--op-type",
            "regen_downstream",
            "--worklist-json",
            json.dumps(worklist),
            "--tier",
            "comparch",
            "--source-scope-json",
            json.dumps({"tier": "sysarch", "comp_id": "proj"}),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    pid = out["propagation_id"]
    assert out["status"] == "open"
    assert out["counts"]["pending"] == 2

    # File is on disk before the calling skill commits it — the writer
    # lays it down, the skill picks it up via git add.
    on_disk = Path(out["state_path"])
    assert on_disk.exists()
    assert on_disk.is_relative_to(repo / "state" / "propagations")

    # Commit so list-propagations (which reads via GitView) can see it.
    subprocess.run(["git", "-C", str(repo), "add", "state/"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "open"], check=True)

    capsys.readouterr()
    rc = main(
        [
            "update-propagation-entry",
            "--repo",
            str(repo),
            "--propagation-id",
            pid,
            "--scope-json",
            json.dumps({"tier": "comparch", "comp_id": "comp_a"}),
            "--status",
            "done",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"] == {"pending": 1, "in_progress": 0, "done": 1, "skipped": 0}

    subprocess.run(["git", "-C", str(repo), "add", "state/"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "drain a"], check=True)

    capsys.readouterr()
    rc = main(["list-propagations", "--repo", str(repo)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["propagations"]) == 1
    assert out["propagations"][0]["propagation_id"] == pid
    assert out["propagations"][0]["status"] == "open"

    # Filter by status — the one record is open, so a complete filter
    # returns nothing.
    capsys.readouterr()
    assert main(["list-propagations", "--repo", str(repo), "--status", "complete"]) == 0
    assert json.loads(capsys.readouterr().out)["propagations"] == []


def test_cli_open_propagation_with_explicit_id(tmp_path: Path, capsys):
    """``--propagation-id`` lets tests + idempotency callers pin the
    record id rather than minting a fresh one each call."""
    repo = _git_repo(tmp_path)
    rc = main(
        [
            "open-propagation",
            "--repo",
            str(repo),
            "--op-type",
            "regen_downstream",
            "--worklist-json",
            "[]",
            "--propagation-id",
            "prop_FIXED",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["propagation_id"] == "prop_FIXED"
    assert (repo / "state" / "propagations" / "prop_FIXED.json").exists()


# ---------------- Construction sanity ----------------


def test_new_propagation_mints_id_when_unspecified():
    prop = new_propagation(op_type="regen_downstream", worklist=[])
    assert prop.propagation_id.startswith("prop_")
    assert len(prop.propagation_id) > len("prop_")
