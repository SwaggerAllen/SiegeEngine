"""End-to-end tests for the writer CLI.

Each test sets up a temp directory shaped like a real project repo,
runs the CLI subcommand, and asserts the on-disk state JSON is valid
and round-trips through ``parse_state``.
"""

from __future__ import annotations

import hashlib
import json

from siege.cli import main, mint_nonce
from siege.state import parse_state


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


def test_write_draft_emits_edges_and_meta(tmp_path):
    """A drafted state file always carries `edges` + `meta` keys, even
    empty — the key set stays stable across writers (the retired skill
    heredocs always wrote them)."""
    body_path = tmp_path / "comparch" / "comp_em" / "body.md"
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
            "comp_em",
            "--body-path",
            "comparch/comp_em/body.md",
        ]
    )
    raw = json.loads((tmp_path / "state" / "comparch" / "comp_em.json").read_text())
    assert raw["edges"] == {}
    assert raw["meta"] == {}


def test_write_review_lenient_missing_finding_sections(tmp_path):
    """write-review accepts a review that omits the finding sections —
    only <score> + <intro> are required. The strict parse_review the
    server uses would reject this; the CLI's write path must not."""
    body_path = tmp_path / "comparch" / "comp_lr" / "body.md"
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
            "comp_lr",
            "--body-path",
            "comparch/comp_lr/body.md",
        ]
    )
    review_path = tmp_path / "comparch" / "comp_lr" / "review.md"
    review_path.write_text(
        "<review>\n<intro>Terse review, no findings listed.</intro>\n<score>61</score>\n</review>"
    )
    rc = main(
        [
            "write-review",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_lr",
            "--review-path",
            "comparch/comp_lr/review.md",
        ]
    )
    assert rc == 0
    state = parse_state(json.loads((tmp_path / "state" / "comparch" / "comp_lr.json").read_text()))
    assert state.status == "reviewed"
    assert state.review is not None and state.review.score == 61


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


def test_write_draft_feature_expansion_derives_manifest(tmp_path):
    """write-draft for feature_expansion materializes a node manifest
    beside the state JSON — one node per <feature> block."""
    body = (
        "<introduction>Intro.</introduction>\n"
        "<features>\n"
        "  <feature><name>Login</name><intent>Users sign in.</intent></feature>\n"
        "  <feature><name>Admin Console</name><intent>Operators manage it.</intent>"
        "<implicit/></feature>\n"
        "</features>\n"
    )
    body_path = tmp_path / "feature_expansion" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "feature_expansion",
            "--comp-id",
            "proj",
            "--body-path",
            "feature_expansion/proj/body.md",
        ]
    )
    assert rc == 0
    manifest_path = tmp_path / "manifest" / "feature_expansion" / "proj.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["substrate"] == {
        "tier": "feature_expansion",
        "comp_id": "proj",
        "parent_id": None,
        "sub_id": None,
    }
    nodes = manifest["nodes"]
    assert [n["name"] for n in nodes] == ["Login", "Admin Console"]
    assert nodes[0]["intent"] == "Users sign in."
    assert nodes[0]["implicit"] is False
    assert nodes[1]["implicit"] is True
    assert all(n["id"].startswith("feat_") for n in nodes)


def test_write_draft_requirements_derives_manifest(tmp_path):
    """write-draft for requirements materializes resp_* nodes, each
    carrying the feat_* ids its <feats> block references."""
    body = (
        "<requirements>\n"
        "  <responsibility><name>session lifecycle</name>"
        '<feats><feat id="feat_aaa"/></feats></responsibility>\n'
        "  <responsibility><name>event log</name><feats/></responsibility>\n"
        "</requirements>\n"
    )
    body_path = tmp_path / "requirements" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "requirements",
            "--comp-id",
            "proj",
            "--body-path",
            "requirements/proj/body.md",
        ]
    )
    assert rc == 0
    manifest = json.loads((tmp_path / "manifest" / "requirements" / "proj.json").read_text())
    nodes = manifest["nodes"]
    assert [n["name"] for n in nodes] == ["session lifecycle", "event log"]
    assert nodes[0]["feats"] == ["feat_aaa"]
    assert nodes[1]["feats"] == []
    assert all(n["id"].startswith("resp_") for n in nodes)


def test_manifest_node_ids_carry_forward(tmp_path):
    """Re-drafting (regen) keeps each node's id stable by name-match."""
    body = "<features>\n  <feature><name>Login</name><intent>v1.</intent></feature>\n</features>\n"
    body_path = tmp_path / "feature_expansion" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    argv = [
        "write-draft",
        "--repo",
        str(tmp_path),
        "--tier",
        "feature_expansion",
        "--comp-id",
        "proj",
        "--body-path",
        "feature_expansion/proj/body.md",
    ]
    main(argv)
    manifest_path = tmp_path / "manifest" / "feature_expansion" / "proj.json"
    first_id = json.loads(manifest_path.read_text())["nodes"][0]["id"]
    # Regen: same feature name, reworded intent.
    body_path.write_text(body.replace("v1.", "v2 — reworded."))
    main(argv)
    second = json.loads(manifest_path.read_text())["nodes"][0]
    assert second["id"] == first_id
    assert second["intent"] == "v2 — reworded."


def test_mark_drafted_resyncs_body_and_clears_review(tmp_path):
    """mark-drafted recomputes the sha for a hand-edited body, drops
    review/approval, returns the scope to `drafted`, and rebuilds the
    node manifest from the edited body."""
    body = "<features>\n  <feature><name>Login</name><intent>v1.</intent></feature>\n</features>\n"
    body_path = tmp_path / "feature_expansion" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    scope_args = ["--tier", "feature_expansion", "--comp-id", "proj"]
    main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            *scope_args,
            "--body-path",
            "feature_expansion/proj/body.md",
        ]
    )
    review_path = tmp_path / "feature_expansion" / "proj" / "review.md"
    review_path.write_text("<review><intro>Fine.</intro><score>80</score></review>")
    main(
        [
            "write-review",
            "--repo",
            str(tmp_path),
            *scope_args,
            "--review-path",
            "feature_expansion/proj/review.md",
        ]
    )
    state_path = tmp_path / "state" / "feature_expansion" / "proj.json"
    assert parse_state(json.loads(state_path.read_text())).status == "reviewed"

    body_path.write_text(body.replace("v1.", "hand-edited."))
    rc = main(["mark-drafted", "--repo", str(tmp_path), *scope_args])
    assert rc == 0
    state = parse_state(json.loads(state_path.read_text()))
    assert state.status == "drafted"
    assert state.review is None
    assert state.draft is not None
    assert state.draft.body_sha256 == hashlib.sha256(body_path.read_bytes()).hexdigest()
    manifest = json.loads((tmp_path / "manifest" / "feature_expansion" / "proj.json").read_text())
    assert manifest["nodes"][0]["intent"] == "hand-edited."


def test_mint_plan_materializes_impl_stubs(tmp_path):
    """mint-plan reads state/plan.json and writes one absent-status
    impl stub per planned node, seeded with the resp closure. A second
    run is idempotent."""
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
    rc = main(["mint-plan", "--repo", str(tmp_path)])
    assert rc == 0
    stub_path = tmp_path / "state" / "impl" / "comp_x" / "p1" / "sub_a.json"
    assert stub_path.exists()
    stub = parse_state(json.loads(stub_path.read_text()))
    assert stub.status == "absent"
    assert stub.scope.phase == 1
    assert stub.meta["parent_resps"] == ["resp_1"]
    # second run re-seeds the absent stub without error
    assert main(["mint-plan", "--repo", str(tmp_path)]) == 0
