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
    _is_downstream,
    add_entries,
    compute_downstream_worklist,
    dump_propagation,
    load_propagation,
    new_propagation,
    read_propagation,
    update_entry,
    write_propagation,
)
from siege.state import DraftBlock, Scope, State, Tier


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


# ---------------- Top-down worklist computation ----------------


def _state(scope: Scope) -> State:
    """Minimal State with a draft block — enough for list_tier to
    surface the scope; the worklist walk only reads scope identity."""
    return State(
        schema_version=1,
        scope=scope,
        status="approved",
        nonce="n",
        draft=DraftBlock(body_path=scope.body_path(), body_sha256="x", generated_at=""),
        review=None,
    )


class _FakeView:
    """A tiny ``GitView`` substitute exposing only the surface
    ``compute_downstream_worklist`` reads — ``list_tier``."""

    def __init__(self, states: list[State]):
        self.ref = "main"
        self.head_sha = "deadbeef"
        self._by_tier: dict[str, list[State]] = {}
        for s in states:
            self._by_tier.setdefault(s.scope.tier, []).append(s)

    def list_tier(self, tier: str) -> list[State]:
        return list(self._by_tier.get(tier, []))


def _sample_states() -> list[State]:
    """A small project: 2 top-level comps (foundation + auth) each
    with 2 subs, each sub with one impl. All substrate roots present."""
    out: list[State] = [
        _state(Scope(tier="feature_expansion", comp_id="proj")),
        _state(Scope(tier="requirements", comp_id="proj")),
        _state(Scope(tier="sysarch", comp_id="proj")),
        _state(Scope(tier="comparch", comp_id="comp_foundation")),
        _state(Scope(tier="comparch", comp_id="comp_auth")),
        _state(Scope(tier="subcomparch", parent_id="comp_foundation", sub_id="sub_storage")),
        _state(Scope(tier="subcomparch", parent_id="comp_foundation", sub_id="sub_config")),
        _state(Scope(tier="subcomparch", parent_id="comp_auth", sub_id="sub_session")),
        _state(Scope(tier="subcomparch", parent_id="comp_auth", sub_id="sub_creds")),
        _state(Scope(tier="impl", parent_id="comp_foundation", sub_id="sub_storage", phase=0)),
        _state(Scope(tier="impl", parent_id="comp_foundation", sub_id="sub_config", phase=0)),
        _state(Scope(tier="impl", parent_id="comp_auth", sub_id="sub_session", phase=0)),
        _state(Scope(tier="impl", parent_id="comp_auth", sub_id="sub_creds", phase=0)),
    ]
    return out


def test_sysarch_source_emits_every_downstream_scope():
    """A substrate-root source covers everything strictly later in
    the chain — including the other substrate roots that aren't above
    it (requirements would be upstream of sysarch, but sysarch's
    downstream is comparch+). For a sysarch source the worklist is:
    every comparch + every subcomparch + every impl."""
    view = _FakeView(_sample_states())
    work = compute_downstream_worklist(view, Scope(tier="sysarch", comp_id="proj"))  # type: ignore[arg-type]
    tiers = sorted({e.scope.tier for e in work})
    assert tiers == ["comparch", "impl", "subcomparch"]
    assert len(work) == 2 + 4 + 4  # 2 comparch + 4 sub + 4 impl


def test_feature_expansion_source_covers_substrate_roots_below():
    """fe source emits requirements + sysarch substrate roots in
    addition to all component-tier scopes. The substrate-root scopes
    are singletons-per-project."""
    view = _FakeView(_sample_states())
    work = compute_downstream_worklist(view, Scope(tier="feature_expansion", comp_id="proj"))  # type: ignore[arg-type]
    tier_counts: dict[str, int] = {}
    for e in work:
        tier_counts[e.scope.tier] = tier_counts.get(e.scope.tier, 0) + 1
    assert tier_counts == {
        "requirements": 1,
        "sysarch": 1,
        "comparch": 2,
        "subcomparch": 4,
        "impl": 4,
    }


def test_comparch_source_restricts_to_its_own_subtree():
    """A comparch source emits only the subcomparches and impls under
    that one comp. Sibling comps are NOT downstream — they're laterally
    related, not in the source's decomposition."""
    view = _FakeView(_sample_states())
    work = compute_downstream_worklist(view, Scope(tier="comparch", comp_id="comp_auth"))  # type: ignore[arg-type]
    # Every emitted scope must belong to comp_auth's subtree.
    for e in work:
        assert e.scope.parent_id == "comp_auth", f"leaked sibling: {e.scope}"
    tiers = sorted({e.scope.tier for e in work})
    assert tiers == ["impl", "subcomparch"]
    # 2 subs + 2 impls under comp_auth.
    assert len(work) == 4


def test_subcomparch_source_emits_only_its_impls():
    view = _FakeView(_sample_states())
    work = compute_downstream_worklist(
        view,  # type: ignore[arg-type]
        Scope(tier="subcomparch", parent_id="comp_auth", sub_id="sub_session"),
    )
    assert len(work) == 1
    assert work[0].scope.tier == "impl"
    assert work[0].scope.parent_id == "comp_auth"
    assert work[0].scope.sub_id == "sub_session"


def test_impl_source_has_no_downstream():
    """Impl is the leaf of the top-down chain. Fanin is bottom-up and
    out of scope for this walk."""
    view = _FakeView(_sample_states())
    work = compute_downstream_worklist(
        view,  # type: ignore[arg-type]
        Scope(tier="impl", parent_id="comp_auth", sub_id="sub_session", phase=0),
    )
    assert work == []


def test_fanin_source_returns_empty_list():
    """Fanin isn't in the top-down chain, so a fanin source returns
    empty — caller should switch to a bottom-up propagation type when
    one exists."""
    view = _FakeView(_sample_states())
    work = compute_downstream_worklist(view, Scope(tier="fanin", comp_id="comp_auth"))  # type: ignore[arg-type]
    assert work == []


def test_worklist_enumerates_only_existing_states():
    """Only states that exist in the substrate count. A comp listed in
    the sysarch ledger but with no comparch state isn't in the
    propagation (it's cold-start work for /run_tier, not regen work)."""
    states = [
        _state(Scope(tier="sysarch", comp_id="proj")),
        _state(Scope(tier="comparch", comp_id="comp_foundation")),
        # comp_auth listed in ledger but no comparch state → skipped.
    ]
    view = _FakeView(states)
    work = compute_downstream_worklist(view, Scope(tier="sysarch", comp_id="proj"))  # type: ignore[arg-type]
    assert [e.scope.comp_id for e in work] == ["comp_foundation"]


def test_empty_project_emits_empty_worklist():
    view = _FakeView([])
    work = compute_downstream_worklist(view, Scope(tier="sysarch", comp_id="proj"))  # type: ignore[arg-type]
    assert work == []


# ---------------- _is_downstream truth table ----------------


def test_is_downstream_substrate_root_covers_everything_later():
    """Substrate-root sources blanket-match every downstream scope —
    the per-source filters only kick in for component-tier sources."""
    sysarch = Scope(tier="sysarch", comp_id="proj")
    assert _is_downstream(Scope(tier="comparch", comp_id="comp_x"), sysarch)
    assert _is_downstream(Scope(tier="subcomparch", parent_id="comp_x", sub_id="sub_y"), sysarch)
    # Upstream doesn't count.
    assert not _is_downstream(Scope(tier="requirements", comp_id="proj"), sysarch)
    # Self doesn't count.
    assert not _is_downstream(Scope(tier="sysarch", comp_id="proj"), sysarch)


def test_is_downstream_comparch_blocks_sibling_subtree():
    """The comparch source ``comp_X`` rejects scopes whose
    ``parent_id != X`` — sibling comps and their subtrees are not
    downstream."""
    comp_x = Scope(tier="comparch", comp_id="comp_x")
    assert _is_downstream(Scope(tier="subcomparch", parent_id="comp_x", sub_id="sub_a"), comp_x)
    assert not _is_downstream(Scope(tier="subcomparch", parent_id="comp_y", sub_id="sub_a"), comp_x)
    assert _is_downstream(Scope(tier="impl", parent_id="comp_x", sub_id="sub_a", phase=0), comp_x)
    assert not _is_downstream(
        Scope(tier="impl", parent_id="comp_y", sub_id="sub_a", phase=0), comp_x
    )


def test_is_downstream_subcomparch_only_matches_same_sub():
    """A subcomparch source matches an impl iff both ``parent_id`` and
    ``sub_id`` align."""
    sub = Scope(tier="subcomparch", parent_id="comp_x", sub_id="sub_a")
    assert _is_downstream(Scope(tier="impl", parent_id="comp_x", sub_id="sub_a", phase=0), sub)
    assert not _is_downstream(Scope(tier="impl", parent_id="comp_x", sub_id="sub_b", phase=0), sub)


# ---------------- CLI: from-source-scope shortcut ----------------


def test_cli_open_propagation_from_source_scope(tmp_path: Path, capsys):
    """The skill flow: open-propagation with --from-source-scope-json
    computes the worklist from the source and writes the record in one
    call — no separate compute step required."""
    repo = _git_repo(tmp_path)
    # Lay down a single subcomparch state file so the walk has
    # something to enumerate when source is sysarch.
    state_dir = repo / "state" / "subcomparch" / "comp_a"
    state_dir.mkdir(parents=True)
    (state_dir / "sub_b.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": {
                    "tier": "subcomparch",
                    "parent_id": "comp_a",
                    "sub_id": "sub_b",
                },
                "status": "approved",
                "nonce": "n",
                "draft": {
                    "body_path": "subcomparch/comp_a/sub_b/body.md",
                    "body_sha256": "x",
                    "generated_at": "",
                },
            }
        )
    )
    subprocess.run(["git", "-C", str(repo), "add", "state/"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)

    capsys.readouterr()
    rc = main(
        [
            "open-propagation",
            "--repo",
            str(repo),
            "--op-type",
            "propagate_downstream",
            "--from-source-scope-json",
            json.dumps({"tier": "sysarch", "comp_id": "proj"}),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    # One entry (the sub_b subcomparch).
    assert out["counts"]["pending"] == 1
    on_disk = Path(out["state_path"])
    payload = json.loads(on_disk.read_text())
    assert payload["worklist"][0]["scope"]["sub_id"] == "sub_b"
    # The source scope is recorded on the record itself.
    assert payload["source_scope"] == {
        "tier": "sysarch",
        "comp_id": "proj",
        "parent_id": None,
        "sub_id": None,
        "phase": None,
    }


def test_cli_open_propagation_rejects_mixed_worklist_and_source(tmp_path: Path):
    """--worklist-json and --from-source-scope-json are mutually
    exclusive. The skill picks one input strategy and sticks with it."""
    repo = _git_repo(tmp_path)
    with pytest.raises(SystemExit, match="mutually exclusive"):
        main(
            [
                "open-propagation",
                "--repo",
                str(repo),
                "--op-type",
                "propagate_downstream",
                "--worklist-json",
                json.dumps([{"scope": {"tier": "comparch", "comp_id": "c"}}]),
                "--from-source-scope-json",
                json.dumps({"tier": "sysarch", "comp_id": "proj"}),
            ]
        )


def test_cli_compute_downstream_preview(tmp_path: Path, capsys):
    """``compute-downstream`` is the standalone preview — same walk,
    output is JSON to stdout, no on-disk record minted."""
    repo = _git_repo(tmp_path)
    state_dir = repo / "state" / "comparch"
    state_dir.mkdir(parents=True)
    (state_dir / "comp_x.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": {"tier": "comparch", "comp_id": "comp_x"},
                "status": "approved",
                "nonce": "n",
                "draft": {
                    "body_path": "comparch/comp_x/body.md",
                    "body_sha256": "x",
                    "generated_at": "",
                },
            }
        )
    )
    subprocess.run(["git", "-C", str(repo), "add", "state/"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)

    capsys.readouterr()
    rc = main(
        [
            "compute-downstream",
            "--repo",
            str(repo),
            "--source-scope-json",
            json.dumps({"tier": "sysarch", "comp_id": "proj"}),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["source_scope"]["tier"] == "sysarch"
    assert len(out["worklist"]) == 1
    assert out["worklist"][0]["scope"]["comp_id"] == "comp_x"
    # No propagation file written.
    assert not (repo / "state" / "propagations").exists()
