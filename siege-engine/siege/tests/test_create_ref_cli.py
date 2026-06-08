"""Tests for the create-ref + list-refs CLI subcommands.

Same harness as test_add_input_doc_cli — captured backend stub + a
real temp git repo so the commit + sha derivation is real.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from siege import backend_client
from siege.cli import main


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    subprocess.run(["git", "config", "tag.gpgsign", "false"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init", "--quiet"], cwd=repo, check=True)
    return repo


@pytest.fixture()
def captured_backend(monkeypatch):
    calls: list[dict] = []
    existing_by_name: dict[str, dict] = {}

    def fake_by_name(project_id, name):
        calls.append({"op": "by_name", "project_id": project_id, "name": name})
        return existing_by_name.get(name)

    def fake_create(project_id, ref_id, name, body_sha, body_path=None):
        rec = {
            "project_id": project_id,
            "ref_id": ref_id,
            "name": name,
            "body_sha": body_sha,
            "body_path": body_path,
        }
        calls.append({"op": "create", **rec})
        result = {
            "id": ref_id,
            "project_id": project_id,
            "name": name,
            "body_sha": body_sha,
            "body_path": body_path or f"refs/{ref_id}/body.md",
            "created_at": "2026-06-03T00:00:00",
            "updated_at": "2026-06-03T00:00:00",
        }
        # Make the row visible to subsequent by_name lookups.
        existing_by_name[name] = result
        return result

    def fake_list(project_id):
        calls.append({"op": "list", "project_id": project_id})
        return list(existing_by_name.values())

    monkeypatch.setattr(backend_client, "get_reference_by_name", fake_by_name)
    monkeypatch.setattr(backend_client, "create_git_reference", fake_create)
    monkeypatch.setattr(backend_client, "list_references", fake_list)
    return calls, existing_by_name


def test_create_ref_writes_body_commits_and_registers(
    fake_repo, captured_backend, tmp_path, capsys
):
    calls, _existing = captured_backend
    content_file = tmp_path / "stripe.md"
    content_file.write_text("Stripe charges through the v2 endpoint require ...")

    rc = main(
        [
            "create-ref",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--name",
            "Stripe API summary",
            "--content-file",
            str(content_file),
            "--no-push",
        ]
    )
    assert rc == 0

    out = json.loads(capsys.readouterr().out.strip())
    ref_id = out["id"]
    assert ref_id.startswith("ref_")
    assert re.match(r"^ref_[0-9A-HJKMNP-TV-Z]{8}$", ref_id)

    # File landed at the default path.
    target = fake_repo / "refs" / ref_id / "body.md"
    assert target.is_file()
    assert "Stripe charges" in target.read_text()

    # Commit landed.
    log = subprocess.check_output(["git", "log", "--oneline"], cwd=fake_repo, text=True)
    assert f"refs: add Stripe API summary ({ref_id})" in log

    # Backend was called with the right body_sha.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fake_repo, text=True).strip()
    create_calls = [c for c in calls if c["op"] == "create"]
    assert len(create_calls) == 1
    call = create_calls[0]
    assert call["ref_id"] == ref_id
    assert call["body_sha"] == head
    assert call["body_path"] == f"refs/{ref_id}/body.md"


def test_create_ref_custom_body_path(fake_repo, captured_backend, tmp_path, capsys):
    calls, _ = captured_backend
    content_file = tmp_path / "memo.md"
    content_file.write_text("memo content")

    rc = main(
        [
            "create-ref",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--name",
            "Design memo",
            "--content-file",
            str(content_file),
            "--body-path",
            "docs/memo.md",
            "--no-push",
        ]
    )
    assert rc == 0
    assert (fake_repo / "docs" / "memo.md").is_file()
    create_calls = [c for c in calls if c["op"] == "create"]
    assert create_calls[0]["body_path"] == "docs/memo.md"


def test_create_ref_duplicate_name_errors_by_default(fake_repo, captured_backend, tmp_path):
    calls, existing_by_name = captured_backend
    # Seed an existing ref with the target name.
    existing_by_name["Already here"] = {
        "id": "ref_PREEXIST",
        "name": "Already here",
        "body_sha": "x" * 64,
        "body_path": "refs/ref_PREEXIST/body.md",
    }
    content_file = tmp_path / "dup.md"
    content_file.write_text("body")

    rc = main(
        [
            "create-ref",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--name",
            "Already here",
            "--content-file",
            str(content_file),
            "--no-push",
        ]
    )
    assert rc == 4
    # Backend create wasn't called.
    assert [c for c in calls if c["op"] == "create"] == []


def test_create_ref_allow_existing_returns_existing(fake_repo, captured_backend, tmp_path, capsys):
    calls, existing_by_name = captured_backend
    existing_by_name["Already here"] = {
        "id": "ref_PREEXIST",
        "name": "Already here",
        "body_sha": "x" * 64,
        "body_path": "refs/ref_PREEXIST/body.md",
    }
    content_file = tmp_path / "dup.md"
    content_file.write_text("body")

    rc = main(
        [
            "create-ref",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--name",
            "Already here",
            "--content-file",
            str(content_file),
            "--allow-existing",
            "--no-push",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["id"] == "ref_PREEXIST"
    assert out.get("preexisting") is True
    # No body file was written under refs/ref_PREEXIST/ since we
    # returned early.
    assert not (fake_repo / "refs" / "ref_PREEXIST" / "body.md").exists()


def test_create_ref_missing_content_file_is_error(fake_repo, captured_backend):
    calls, _ = captured_backend
    rc = main(
        [
            "create-ref",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--name",
            "X",
            "--content-file",
            "/does/not/exist.md",
            "--no-push",
        ]
    )
    assert rc == 2
    assert [c for c in calls if c["op"] == "create"] == []


def test_list_refs(captured_backend, capsys):
    calls, existing_by_name = captured_backend
    existing_by_name["A"] = {
        "id": "ref_A",
        "name": "A",
        "body_sha": "a",
        "body_path": "refs/ref_A/body.md",
    }
    rc = main(["list-refs", "--project-id", "proj_1"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert len(out["references"]) == 1
    assert out["references"][0]["id"] == "ref_A"
