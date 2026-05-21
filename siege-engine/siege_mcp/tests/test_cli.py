"""End-to-end tests for the writer CLI.

Each test sets up a temp directory shaped like a real project repo,
runs the CLI subcommand, and asserts the on-disk state JSON is valid
and round-trips through ``parse_state``.
"""

from __future__ import annotations

import json

from siege_mcp.cli import main, mint_nonce
from siege_mcp.state import parse_state


def _run(monkeypatch, argv):
    rc = main(argv)
    return rc


def test_mint_nonce_format():
    n = mint_nonce()
    assert len(n) == 26
    assert all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUV" for c in n)


def test_write_draft_creates_state(tmp_path, monkeypatch, capsys):
    # Set up body file
    body_path = tmp_path / "comparch" / "comp_a" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## comparch:techspec\nfoo\n\n## comparch:pubapi\nbar\n")

    rc = _run(
        monkeypatch,
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_a",
            "--body-path",
            "comparch/comp_a/body.md",
        ],
    )
    assert rc == 0
    state_file = tmp_path / "state" / "comparch" / "comp_a.json"
    assert state_file.exists()
    state = parse_state(json.loads(state_file.read_text()))
    assert state.status == "drafted"
    assert state.scope.comp_id == "comp_a"
    assert state.draft is not None
    assert state.draft.body_path == "comparch/comp_a/body.md"
    assert len(state.draft.body_sha256) == 64


def test_write_draft_validate_failure(tmp_path, monkeypatch):
    body_path = tmp_path / "comparch" / "comp_b" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("")  # empty body triggers validate failure
    rc = _run(
        monkeypatch,
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_b",
            "--body-path",
            "comparch/comp_b/body.md",
        ],
    )
    assert rc == 3
    assert not (tmp_path / "state" / "comparch" / "comp_b.json").exists()


def test_write_draft_then_review(tmp_path, monkeypatch):
    body_path = tmp_path / "comparch" / "comp_c" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## comparch:techspec\na\n\n## comparch:pubapi\nb\n")
    rc = _run(
        monkeypatch,
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_c",
            "--body-path",
            "comparch/comp_c/body.md",
        ],
    )
    assert rc == 0

    review_path = tmp_path / "comparch" / "comp_c" / "review.md"
    review_path.write_text(
        """<review>
  <intro>Looks good overall, two minor structural notes.</intro>
  <score>78</score>
  <handles-structure>
    <finding id="h1">Handle X is used inconsistently.</finding>
  </handles-structure>
  <architectural-decisions>
    <finding id="a1">Decision on storage backend is implicit.</finding>
  </architectural-decisions>
</review>"""
    )
    rc = _run(
        monkeypatch,
        [
            "write-review",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_c",
            "--review-path",
            "comparch/comp_c/review.md",
        ],
    )
    assert rc == 0
    state = parse_state(json.loads((tmp_path / "state" / "comparch" / "comp_c.json").read_text()))
    assert state.status == "reviewed"
    assert state.review is not None
    assert state.review.score == 78


def test_approval_path(tmp_path):
    body_path = tmp_path / "comparch" / "comp_d" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## comparch:techspec\na\n\n## comparch:pubapi\nb\n")
    main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_d",
            "--body-path",
            "comparch/comp_d/body.md",
        ]
    )
    review_path = tmp_path / "comparch" / "comp_d" / "review.md"
    review_path.write_text(
        """<review>
  <intro>Solid.</intro>
  <score>92</score>
  <handles-structure></handles-structure>
  <architectural-decisions></architectural-decisions>
</review>"""
    )
    main(
        [
            "write-review",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_d",
            "--review-path",
            "comparch/comp_d/review.md",
        ]
    )

    rc = main(
        [
            "write-approval",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_d",
            "--approver",
            "alice@example.com",
        ]
    )
    assert rc == 0
    state = parse_state(json.loads((tmp_path / "state" / "comparch" / "comp_d.json").read_text()))
    assert state.status == "approved"
    assert state.approval is not None
    assert state.approval.approved_by == "alice@example.com"


def test_repair_drift(tmp_path):
    body_path = tmp_path / "comparch" / "comp_e" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## comparch:techspec\na\n\n## comparch:pubapi\nb\n")
    main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_e",
            "--body-path",
            "comparch/comp_e/body.md",
        ]
    )
    # Mutate body without re-running draft → drift
    body_path.write_text("## comparch:techspec\nNEW\n\n## comparch:pubapi\nb\n")

    rc = main(
        [
            "repair-drift",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_e",
        ]
    )
    assert rc == 0
    state = parse_state(json.loads((tmp_path / "state" / "comparch" / "comp_e.json").read_text()))
    # New sha matches the new body bytes
    import hashlib

    expected = hashlib.sha256(body_path.read_bytes()).hexdigest()
    assert state.draft is not None
    assert state.draft.body_sha256 == expected


def test_mint_batch(tmp_path):
    rc = main(
        [
            "mint-batch",
            "--repo",
            str(tmp_path),
            "--op-type",
            "regen_below_threshold",
            "--tier",
            "comparch",
            "--threshold",
            "70",
            "--scopes-json",
            '[{"tier":"comparch","comp_id":"comp_a"}]',
        ]
    )
    assert rc == 0
    batches = list((tmp_path / "state" / "batches").iterdir())
    assert len(batches) == 1
    payload = json.loads(batches[0].read_text())
    assert payload["op_type"] == "regen_below_threshold"
    assert payload["threshold"] == 70
    assert payload["scopes"] == [{"tier": "comparch", "comp_id": "comp_a"}]


def test_phased_impl_draft_writes_v2_at_phase_path(tmp_path):
    """write-draft --tier impl --phase 2 lands the state JSON at the
    phased path and stamps schema_version 2."""
    body_path = tmp_path / "impl" / "comp_p" / "subs" / "sub_x" / "p2" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## impl:approach\nphase-2 work\n")
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "impl",
            "--parent-id",
            "comp_p",
            "--sub-id",
            "sub_x",
            "--phase",
            "2",
            "--body-path",
            "impl/comp_p/subs/sub_x/p2/body.md",
        ]
    )
    assert rc == 0
    state_file = tmp_path / "state" / "impl" / "comp_p" / "p2" / "sub_x.json"
    assert state_file.exists()
    state = parse_state(json.loads(state_file.read_text()))
    assert state.schema_version == 2
    assert state.scope.phase == 2
    assert state.scope.parent_id == "comp_p"
    assert state.scope.sub_id == "sub_x"


def test_unphased_impl_draft_keeps_v1_legacy_path(tmp_path):
    """Omitting --phase yields the byte-identical legacy v1 shape:
    state/impl/<parent>/<sub>.json, schema_version 1, phase None."""
    body_path = tmp_path / "impl" / "comp_q" / "subs" / "sub_y" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## impl:approach\nunphased work\n")
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "impl",
            "--parent-id",
            "comp_q",
            "--sub-id",
            "sub_y",
            "--body-path",
            "impl/comp_q/subs/sub_y/body.md",
        ]
    )
    assert rc == 0
    state_file = tmp_path / "state" / "impl" / "comp_q" / "sub_y.json"
    assert state_file.exists()
    state = parse_state(json.loads(state_file.read_text()))
    assert state.schema_version == 1
    assert state.scope.phase is None


def test_sub_tier_paths(tmp_path):
    body_path = tmp_path / "subcomparch" / "comp_p" / "subs" / "sub_x" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text("## subcomparch:techspec\nx\n\n## subcomparch:pubapi\ny\n")
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "subcomparch",
            "--parent-id",
            "comp_p",
            "--sub-id",
            "sub_x",
            "--body-path",
            "subcomparch/comp_p/subs/sub_x/body.md",
        ]
    )
    assert rc == 0
    state_file = tmp_path / "state" / "subcomparch" / "comp_p" / "sub_x.json"
    assert state_file.exists()
    state = parse_state(json.loads(state_file.read_text()))
    assert state.scope.parent_id == "comp_p"
    assert state.scope.sub_id == "sub_x"
