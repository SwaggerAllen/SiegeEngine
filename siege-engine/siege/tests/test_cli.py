"""End-to-end tests for the writer CLI.

Each test sets up a temp directory shaped like a real project repo,
runs the CLI subcommand, and asserts the on-disk state JSON is valid
and round-trips through ``parse_state``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess

from siege.cli import main, mint_nonce
from siege.state import parse_state


def _git_repo(root):
    """Init a scratch git repo (signing off — this is a test fixture)."""
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True)
    return root


def _git_commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True)


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
    """write-draft for feature_expansion materializes a slim identity
    ledger beside the state JSON — one node per <feature> block."""
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
    ledger_path = tmp_path / "ids" / "feature_expansion" / "proj.json"
    assert ledger_path.exists()
    manifest = json.loads(ledger_path.read_text())
    assert manifest["schema_version"] == 2
    assert manifest["substrate"] == {
        "tier": "feature_expansion",
        "comp_id": "proj",
        "parent_id": None,
        "sub_id": None,
    }
    nodes = manifest["nodes"]
    assert [n["name"] for n in nodes] == ["Login", "Admin Console"]
    # The persisted ledger is slim — identity only, no projectable fields.
    assert all(set(n) == {"id", "name"} for n in nodes)
    assert all(n["id"].startswith("feat_") for n in nodes)


def test_write_draft_requirements_derives_manifest(tmp_path):
    """write-draft for requirements materializes a slim resp_* ledger
    (id + name); the <feats> edges are re-derived at projection time."""
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
    manifest = json.loads((tmp_path / "ids" / "requirements" / "proj.json").read_text())
    nodes = manifest["nodes"]
    assert [n["name"] for n in nodes] == ["session lifecycle", "event log"]
    # Slim ledger — the resp->feat edges are re-derived from the body, not stored.
    assert all(set(n) == {"id", "name"} for n in nodes)
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
    ledger_path = tmp_path / "ids" / "feature_expansion" / "proj.json"
    first_id = json.loads(ledger_path.read_text())["nodes"][0]["id"]
    # Regen: same feature name, reworded intent. The id carries forward
    # by name — derive loaded the prior id from the slim ledger.
    body_path.write_text(body.replace("v1.", "v2 — reworded."))
    main(argv)
    second = json.loads(ledger_path.read_text())["nodes"][0]
    assert second["id"] == first_id
    assert second["name"] == "Login"


def test_mark_drafted_resyncs_body_and_clears_review(tmp_path):
    """mark-drafted recomputes the sha for a hand-edited body, drops
    review/approval, returns the scope to `drafted`, and rebuilds the
    identity ledger from the edited body."""
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

    edited = (
        "<features>\n"
        "  <feature><name>Login</name><intent>v1.</intent></feature>\n"
        "  <feature><name>Logout</name><intent>End session.</intent></feature>\n"
        "</features>\n"
    )
    body_path.write_text(edited)
    rc = main(["mark-drafted", "--repo", str(tmp_path), *scope_args])
    assert rc == 0
    state = parse_state(json.loads(state_path.read_text()))
    assert state.status == "drafted"
    assert state.review is None
    assert state.draft is not None
    assert state.draft.body_sha256 == hashlib.sha256(body_path.read_bytes()).hexdigest()
    # The ledger was rebuilt from the hand-edited body — the added
    # feature shows up as a second slim node.
    manifest = json.loads((tmp_path / "ids" / "feature_expansion" / "proj.json").read_text())
    assert [n["name"] for n in manifest["nodes"]] == ["Login", "Logout"]


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


# ---------------- sysarch / comparch identity ledger (step 4) ----------------

_SYSARCH_BODY = (
    "## project_techspec\n\nx\n\n"
    "<components>\n"
    '  <component alias="foundation"><name>Foundation</name><foundation/></component>\n'
    '  <component alias="billing"><name>Billing Service</name></component>\n'
    "</components>\n"
)


def test_write_draft_sysarch_derives_ledger(tmp_path):
    """write-draft for sysarch materializes a slim identity ledger —
    one comp_* node per <component>, keyed by alias."""
    body_path = tmp_path / "sysarch" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(_SYSARCH_BODY)
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "sysarch",
            "--comp-id",
            "proj",
            "--body-path",
            "sysarch/proj/body.md",
        ]
    )
    assert rc == 0
    ledger = json.loads((tmp_path / "ids" / "sysarch" / "proj.json").read_text())
    assert ledger["schema_version"] == 2
    nodes = ledger["nodes"]
    assert [n["alias"] for n in nodes] == ["foundation", "billing"]
    # Slim ledger — id + alias only, no projectable fields.
    assert all(set(n) == {"id", "alias"} for n in nodes)
    assert all(n["id"].startswith("comp_") for n in nodes)


def test_write_draft_comparch_derives_ledger(tmp_path):
    """write-draft for comparch materializes a slim identity ledger —
    one comp_* node per <subcomponent>, keyed by alias."""
    body = (
        "## comparch:techspec\n\nx\n\n## comparch:pubapi\n\ny\n\n"
        "<subcomponents>\n"
        '  <subcomponent alias="store"><name>SessionStore</name></subcomponent>\n'
        '  <subcomponent alias="foundation"><name>AuthCore</name><foundation/></subcomponent>\n'
        "</subcomponents>\n"
    )
    body_path = tmp_path / "comparch" / "comp_x" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    rc = main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_x",
            "--body-path",
            "comparch/comp_x/body.md",
        ]
    )
    assert rc == 0
    ledger = json.loads((tmp_path / "ids" / "comparch" / "comp_x.json").read_text())
    nodes = ledger["nodes"]
    assert [n["alias"] for n in nodes] == ["store", "foundation"]
    assert all(set(n) == {"id", "alias"} for n in nodes)
    assert all(n["id"].startswith("comp_") for n in nodes)


def test_ledger_alias_carry_forward(tmp_path):
    """Regen keeps a node's id when its alias is unchanged (even if the
    display <name> drifts), and mints a fresh id when the alias changes."""
    body_path = tmp_path / "sysarch" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(_SYSARCH_BODY)
    argv = [
        "write-draft",
        "--repo",
        str(tmp_path),
        "--tier",
        "sysarch",
        "--comp-id",
        "proj",
        "--body-path",
        "sysarch/proj/body.md",
    ]
    main(argv)
    ledger_path = tmp_path / "ids" / "sysarch" / "proj.json"
    first = {n["alias"]: n["id"] for n in json.loads(ledger_path.read_text())["nodes"]}

    # Rename the display <name> but keep alias="billing" → id is stable.
    body_path.write_text(_SYSARCH_BODY.replace("Billing Service", "Payments"))
    main(argv)
    after_rename = {n["alias"]: n["id"] for n in json.loads(ledger_path.read_text())["nodes"]}
    assert after_rename["billing"] == first["billing"]

    # Change the alias → a fresh id; the old alias is gone.
    body_path.write_text(_SYSARCH_BODY.replace('alias="billing"', 'alias="payments"'))
    main(argv)
    after_realias = {n["alias"]: n["id"] for n in json.loads(ledger_path.read_text())["nodes"]}
    assert "billing" not in after_realias
    assert after_realias["payments"] != first["billing"]
    assert after_realias["foundation"] == first["foundation"]


def test_list_scopes_comparch(tmp_path, capsys):
    """list-scopes --tier comparch enumerates one scope per component
    in the sysarch ledger, foundation-first, and reflects draft status."""
    body_path = tmp_path / "sysarch" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(_SYSARCH_BODY)
    main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "sysarch",
            "--comp-id",
            "proj",
            "--body-path",
            "sysarch/proj/body.md",
        ]
    )
    capsys.readouterr()
    assert main(["list-scopes", "--repo", str(tmp_path), "--tier", "comparch"]) == 0
    scopes = json.loads(capsys.readouterr().out)["scopes"]
    assert [s["alias"] for s in scopes] == ["foundation", "billing"]
    assert scopes[0]["is_foundation"] is True
    assert all(s["status"] == "absent" for s in scopes)
    assert all(s["comp_id"].startswith("comp_") for s in scopes)

    # Draft the billing comparch → its scope flips to 'drafted'.
    billing_id = next(s["comp_id"] for s in scopes if s["alias"] == "billing")
    cbody = tmp_path / "comparch" / billing_id / "body.md"
    cbody.parent.mkdir(parents=True)
    cbody.write_text("## comparch:techspec\n\nx\n\n## comparch:pubapi\n\ny\n")
    main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            billing_id,
            "--body-path",
            f"comparch/{billing_id}/body.md",
        ]
    )
    capsys.readouterr()
    main(["list-scopes", "--repo", str(tmp_path), "--tier", "comparch"])
    by_alias = {s["alias"]: s["status"] for s in json.loads(capsys.readouterr().out)["scopes"]}
    assert by_alias["billing"] == "drafted"
    assert by_alias["foundation"] == "absent"


def test_list_scopes_subcomparch(tmp_path, capsys):
    """list-scopes --tier subcomparch enumerates (parent_id, sub_id)
    pairs from every comparch ledger."""
    body = (
        "## comparch:techspec\n\nx\n\n## comparch:pubapi\n\ny\n\n"
        "<subcomponents>\n"
        '  <subcomponent alias="store"><name>Store</name></subcomponent>\n'
        '  <subcomponent alias="foundation"><name>Core</name><foundation/></subcomponent>\n'
        "</subcomponents>\n"
    )
    body_path = tmp_path / "comparch" / "comp_p" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    main(
        [
            "write-draft",
            "--repo",
            str(tmp_path),
            "--tier",
            "comparch",
            "--comp-id",
            "comp_p",
            "--body-path",
            "comparch/comp_p/body.md",
        ]
    )
    capsys.readouterr()
    assert main(["list-scopes", "--repo", str(tmp_path), "--tier", "subcomparch"]) == 0
    scopes = json.loads(capsys.readouterr().out)["scopes"]
    assert [s["alias"] for s in scopes] == ["foundation", "store"]
    assert all(s["parent_id"] == "comp_p" for s in scopes)
    assert all(s["sub_id"].startswith("comp_") for s in scopes)
    assert all(s["status"] == "absent" for s in scopes)


# ---------------- read subcommands (step 5) ----------------


def test_get_state_reads_the_committed_tree(tmp_path, capsys):
    """get-state projects the committed git tree at HEAD."""
    repo = _git_repo(tmp_path)
    body = tmp_path / "feature_expansion" / "proj" / "body.md"
    body.parent.mkdir(parents=True)
    body.write_text(
        "## summary\n\nx\n\n<features>\n"
        "  <feature><name>Login</name><intent>i</intent></feature>\n"
        "</features>\n"
    )
    main(
        [
            "write-draft",
            "--repo",
            str(repo),
            "--tier",
            "feature_expansion",
            "--comp-id",
            "proj",
            "--body-path",
            "feature_expansion/proj/body.md",
        ]
    )
    _git_commit(repo, "draft fe")
    capsys.readouterr()
    rc = main(
        ["get-state", "--repo", str(repo), "--tier", "feature_expansion", "--comp-id", "proj"]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["found"] is True
    assert out["status"] == "drafted"
    assert out["ref_head_sha"]


def test_get_state_absent_scope(tmp_path, capsys):
    """get-state on a scope with no committed state reports found=False."""
    repo = _git_repo(tmp_path)
    (tmp_path / "README").write_text("x")
    _git_commit(repo, "init")
    capsys.readouterr()
    rc = main(["get-state", "--repo", str(repo), "--tier", "sysarch", "--comp-id", "nope"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["found"] is False


def test_get_context_rehydrates_the_ledger(tmp_path, capsys):
    """get-context for requirements re-derives the feature nodes from the
    committed feature_expansion ledger + body (the projection path)."""
    repo = _git_repo(tmp_path)
    body = tmp_path / "feature_expansion" / "proj" / "body.md"
    body.parent.mkdir(parents=True)
    body.write_text(
        "## summary\n\nx\n\n<features>\n"
        "  <feature><name>Login</name><intent>Auth.</intent></feature>\n"
        "</features>\n"
    )
    main(
        [
            "write-draft",
            "--repo",
            str(repo),
            "--tier",
            "feature_expansion",
            "--comp-id",
            "proj",
            "--body-path",
            "feature_expansion/proj/body.md",
        ]
    )
    _git_commit(repo, "draft fe")
    capsys.readouterr()
    rc = main(["get-context", "--repo", str(repo), "--tier", "requirements", "--comp-id", "proj"])
    assert rc == 0
    feats = json.loads(capsys.readouterr().out)["features"]
    assert [f["name"] for f in feats] == ["Login"]
    assert feats[0]["intent"] == "Auth."
    assert feats[0]["id"].startswith("feat_")
