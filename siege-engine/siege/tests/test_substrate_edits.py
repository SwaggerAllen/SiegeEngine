"""End-to-end tests for the substrate-edit CLI subcommands.

Covers ``add-feature`` / ``remove-feature`` / ``add-responsibility`` /
``remove-responsibility`` — mechanical body mutations against the
feature_expansion / requirements substrate roots. Each pair:

- read existing body + state
- mutate the body in place
- re-derive the slim identity ledger
- flip state back to ``drafted`` with a fresh sha + nonce, clearing
  any prior review/approval blocks

The remove ops accept both ``--feat-id`` / ``--resp-id`` (resolved
through the ledger) and ``--name`` (matched directly against the
body's ``<name>`` text). The add ops surface the minted ``feat_*`` /
``resp_*`` ID on stdout so the calling skill can echo it.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from siege.cli import main
from siege.state import parse_state


def _seed_features(tmp_path):
    body = (
        "<features>\n"
        "  <feature><name>Login</name><intent>Users sign in.</intent></feature>\n"
        "  <feature><name>Logout</name><intent>End session.</intent></feature>\n"
        "</features>\n"
    )
    body_path = tmp_path / "feature_expansion" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    main(
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
    return body_path


def _seed_requirements(tmp_path, feat_ids: list[str]) -> None:
    feats_xml = "".join(f'<feat id="{fid}"/>' for fid in feat_ids)
    body = (
        "<requirements>\n"
        f"  <responsibility><name>Authentication</name><feats>{feats_xml}</feats>"
        "</responsibility>\n"
        "</requirements>\n"
    )
    body_path = tmp_path / "requirements" / "proj" / "body.md"
    body_path.parent.mkdir(parents=True)
    body_path.write_text(body)
    main(
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


def test_add_feature_appends_block_and_mints_id(tmp_path, capsys):
    body_path = _seed_features(tmp_path)
    capsys.readouterr()

    rc = main(
        [
            "add-feature",
            "--repo",
            str(tmp_path),
            "--name",
            "Subscription Management",
            "--intent",
            "Customers change tiers.",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "add-feature"
    assert out["feat_id"].startswith("feat_")
    assert out["name"] == "Subscription Management"
    # Body has three features now, in declaration order.
    text = body_path.read_text()
    assert text.count("<feature>") == 3
    assert "<name>Subscription Management</name>" in text
    # Ledger gained the new feat.
    ledger = json.loads((tmp_path / "ids" / "feature_expansion" / "proj.json").read_text())
    names = [n["name"] for n in ledger["nodes"]]
    assert names == ["Login", "Logout", "Subscription Management"]
    # State is back to drafted with the new body's sha.
    state_path = tmp_path / "state" / "feature_expansion" / "proj.json"
    state = parse_state(json.loads(state_path.read_text()))
    assert state.status == "drafted"
    assert state.draft is not None
    assert state.draft.body_sha256 == hashlib.sha256(body_path.read_bytes()).hexdigest()


def test_add_feature_with_implicit_flag_emits_implicit_marker(tmp_path, capsys):
    body_path = _seed_features(tmp_path)
    capsys.readouterr()
    rc = main(
        [
            "add-feature",
            "--repo",
            str(tmp_path),
            "--name",
            "Durable Persistence",
            "--intent",
            "Survives disk-level recovery.",
            "--implicit",
        ]
    )
    assert rc == 0
    # The block carries an <implicit/> marker the projection picks up.
    text = body_path.read_text()
    block = [line for line in text.splitlines() if "Durable Persistence" in line][0]
    assert "<implicit/>" in block


def test_add_feature_refuses_duplicate_name(tmp_path):
    _seed_features(tmp_path)
    rc = main(
        [
            "add-feature",
            "--repo",
            str(tmp_path),
            "--name",
            "Login",
            "--intent",
            "Dup.",
        ]
    )
    assert rc == 2  # already exists


def test_remove_feature_by_name(tmp_path, capsys):
    body_path = _seed_features(tmp_path)
    capsys.readouterr()

    rc = main(
        [
            "remove-feature",
            "--repo",
            str(tmp_path),
            "--name",
            "Logout",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "remove-feature"
    assert out["removed_name"] == "Logout"
    # Body lost the Logout block.
    text = body_path.read_text()
    assert "Logout" not in text
    assert text.count("<feature>") == 1
    # Ledger no longer carries the dropped node.
    ledger = json.loads((tmp_path / "ids" / "feature_expansion" / "proj.json").read_text())
    assert [n["name"] for n in ledger["nodes"]] == ["Login"]


def test_remove_feature_by_feat_id(tmp_path, capsys):
    body_path = _seed_features(tmp_path)
    ledger = json.loads((tmp_path / "ids" / "feature_expansion" / "proj.json").read_text())
    logout_id = next(n["id"] for n in ledger["nodes"] if n["name"] == "Logout")
    capsys.readouterr()

    rc = main(
        [
            "remove-feature",
            "--repo",
            str(tmp_path),
            "--feat-id",
            logout_id,
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["removed_name"] == "Logout"
    assert "Logout" not in body_path.read_text()


def test_remove_feature_errors_when_neither_flag_given(tmp_path):
    _seed_features(tmp_path)
    with pytest.raises(SystemExit, match="must pass"):
        main(["remove-feature", "--repo", str(tmp_path)])


def test_remove_feature_errors_when_both_flags_given(tmp_path):
    _seed_features(tmp_path)
    with pytest.raises(SystemExit, match="not both"):
        main(
            [
                "remove-feature",
                "--repo",
                str(tmp_path),
                "--feat-id",
                "feat_anything",
                "--name",
                "Login",
            ]
        )


def test_remove_feature_errors_when_id_unknown(tmp_path):
    _seed_features(tmp_path)
    with pytest.raises(SystemExit, match="not found"):
        main(
            [
                "remove-feature",
                "--repo",
                str(tmp_path),
                "--feat-id",
                "feat_unknown_id",
            ]
        )


def test_add_responsibility_appends_block_with_feat_ids(tmp_path, capsys):
    _seed_features(tmp_path)
    fe_ledger = json.loads((tmp_path / "ids" / "feature_expansion" / "proj.json").read_text())
    login_id = next(n["id"] for n in fe_ledger["nodes"] if n["name"] == "Login")
    _seed_requirements(tmp_path, feat_ids=[login_id])
    capsys.readouterr()

    rc = main(
        [
            "add-responsibility",
            "--repo",
            str(tmp_path),
            "--name",
            "Session Lifecycle",
            "--feat-ids",
            login_id,
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["resp_id"].startswith("resp_")
    assert out["feat_ids"] == [login_id]
    body_path = tmp_path / "requirements" / "proj" / "body.md"
    text = body_path.read_text()
    assert "<name>Session Lifecycle</name>" in text
    assert f'<feat id="{login_id}"/>' in text


def test_add_responsibility_rejects_unknown_feat_id(tmp_path):
    _seed_features(tmp_path)
    _seed_requirements(tmp_path, feat_ids=[])
    rc = main(
        [
            "add-responsibility",
            "--repo",
            str(tmp_path),
            "--name",
            "Audit",
            "--feat-ids",
            "feat_does_not_exist",
        ]
    )
    assert rc == 2


def test_add_responsibility_with_no_feat_ids(tmp_path):
    """Resps tracing to no specific feature (owned platform work) are
    permitted — the validator must not require --feat-ids."""
    _seed_features(tmp_path)
    _seed_requirements(tmp_path, feat_ids=[])
    rc = main(
        [
            "add-responsibility",
            "--repo",
            str(tmp_path),
            "--name",
            "Foundation",
        ]
    )
    assert rc == 0
    text = (tmp_path / "requirements" / "proj" / "body.md").read_text()
    assert "<feats></feats>" in text or "<feats/>" in text


def test_remove_responsibility_by_name(tmp_path, capsys):
    _seed_features(tmp_path)
    _seed_requirements(tmp_path, feat_ids=[])
    capsys.readouterr()

    rc = main(
        [
            "remove-responsibility",
            "--repo",
            str(tmp_path),
            "--name",
            "Authentication",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["removed_name"] == "Authentication"
    body = (tmp_path / "requirements" / "proj" / "body.md").read_text()
    assert "Authentication" not in body
    ledger = json.loads((tmp_path / "ids" / "requirements" / "proj.json").read_text())
    assert ledger["nodes"] == []


def test_remove_responsibility_by_resp_id(tmp_path, capsys):
    _seed_features(tmp_path)
    _seed_requirements(tmp_path, feat_ids=[])
    ledger = json.loads((tmp_path / "ids" / "requirements" / "proj.json").read_text())
    auth_id = ledger["nodes"][0]["id"]
    capsys.readouterr()

    rc = main(
        [
            "remove-responsibility",
            "--repo",
            str(tmp_path),
            "--resp-id",
            auth_id,
        ]
    )
    assert rc == 0
    body = (tmp_path / "requirements" / "proj" / "body.md").read_text()
    assert "Authentication" not in body


def test_edit_clears_review_block(tmp_path):
    """A substrate edit re-syncs state to ``drafted`` — any prior
    review/approval block is dropped because the body changed."""
    _seed_features(tmp_path)
    # Land a review against the seed body, flipping state to reviewed.
    review_path = tmp_path / "feature_expansion" / "proj" / "review.md"
    review_path.write_text("<review><intro>Solid.</intro><score>80</score></review>")
    main(
        [
            "write-review",
            "--repo",
            str(tmp_path),
            "--tier",
            "feature_expansion",
            "--comp-id",
            "proj",
            "--review-path",
            "feature_expansion/proj/review.md",
        ]
    )
    state_path = tmp_path / "state" / "feature_expansion" / "proj.json"
    assert parse_state(json.loads(state_path.read_text())).status == "reviewed"

    main(
        [
            "add-feature",
            "--repo",
            str(tmp_path),
            "--name",
            "New",
            "--intent",
            "x",
        ]
    )
    state = parse_state(json.loads(state_path.read_text()))
    assert state.status == "drafted"
    assert state.review is None
    assert state.approval is None
