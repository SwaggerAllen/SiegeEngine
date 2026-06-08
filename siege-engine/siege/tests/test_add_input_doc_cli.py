"""Tests for the add-input-doc + list-input-docs CLI subcommands.

These exercise the CLI surface end-to-end against a captured
backend stub (we don't want to actually hit a real Catapult
backend in tests). The git operations run against a real temp
repo so the commit + sha derivation path is real.
"""

from __future__ import annotations

import json
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
    # Disable signing — sandboxes may have signing configured globally.
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    subprocess.run(["git", "config", "tag.gpgsign", "false"], cwd=repo, check=True)
    # Need an initial commit so HEAD resolves.
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init", "--quiet"], cwd=repo, check=True)
    return repo


@pytest.fixture()
def captured_backend(monkeypatch):
    """Replace backend_client's HTTP calls with a captured stub."""
    calls: list[dict] = []

    def fake_create(project_id, role, name, body_sha, body_path=None):
        record = {
            "project_id": project_id,
            "role": role,
            "name": name,
            "body_sha": body_sha,
            "body_path": body_path,
        }
        calls.append({"op": "create", **record})
        return {
            "id": "doc_FAKE000001",
            "project_id": project_id,
            "name": name,
            "doc_type": role,
            "body_sha": body_sha,
            "body_path": body_path or f"inputs/{role}.md",
            "created_at": "2026-06-03T00:00:00",
            "updated_at": "2026-06-03T00:00:00",
        }

    def fake_list(project_id):
        calls.append({"op": "list", "project_id": project_id})
        return [
            {
                "id": "doc_A",
                "project_id": project_id,
                "name": "Spec",
                "doc_type": "project_doc",
                "body_sha": "abc",
                "body_path": "inputs/project_doc.md",
                "created_at": "2026-06-03T00:00:00",
                "updated_at": "2026-06-03T00:00:00",
            }
        ]

    monkeypatch.setattr(backend_client, "create_input_document", fake_create)
    monkeypatch.setattr(backend_client, "list_input_documents", fake_list)
    return calls


def test_add_input_doc_writes_file_commits_and_registers(
    fake_repo, captured_backend, tmp_path, capsys
):
    content_file = tmp_path / "seed.md"
    content_file.write_text("# My project\n\nA tracker for X.\n")

    rc = main(
        [
            "add-input-doc",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--role",
            "project_doc",
            "--name",
            "Initial Spec",
            "--content-file",
            str(content_file),
            "--no-push",
        ]
    )
    assert rc == 0

    # File landed in the repo at the bundle-default path.
    target = fake_repo / "inputs" / "project_doc.md"
    assert target.is_file()
    assert "tracker for X" in target.read_text()

    # Commit was made.
    log = subprocess.check_output(["git", "log", "--oneline"], cwd=fake_repo, text=True)
    assert "inputs: add project_doc (Initial Spec)" in log

    # Backend was called with the body_sha derived from HEAD.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fake_repo, text=True).strip()
    create_calls = [c for c in captured_backend if c["op"] == "create"]
    assert len(create_calls) == 1
    call = create_calls[0]
    assert call["project_id"] == "proj_1"
    assert call["role"] == "project_doc"
    assert call["name"] == "Initial Spec"
    assert call["body_sha"] == head
    assert call["body_path"] == "inputs/project_doc.md"

    # Output JSON is parseable + has the doc id.
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["id"] == "doc_FAKE000001"
    assert parsed["body_sha"] == head


def test_add_input_doc_custom_body_path(fake_repo, captured_backend, tmp_path, capsys):
    content_file = tmp_path / "x.md"
    content_file.write_text("custom-path content")

    rc = main(
        [
            "add-input-doc",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--role",
            "domain_spec",
            "--name",
            "Domain",
            "--content-file",
            str(content_file),
            "--body-path",
            "docs/domain.md",
            "--no-push",
        ]
    )
    assert rc == 0
    assert (fake_repo / "docs" / "domain.md").is_file()
    create_calls = [c for c in captured_backend if c["op"] == "create"]
    assert create_calls[0]["body_path"] == "docs/domain.md"


def test_add_input_doc_missing_content_file_is_error(fake_repo, captured_backend):
    rc = main(
        [
            "add-input-doc",
            "--repo",
            str(fake_repo),
            "--project-id",
            "proj_1",
            "--role",
            "project_doc",
            "--name",
            "x",
            "--content-file",
            "/does/not/exist.md",
            "--no-push",
        ]
    )
    assert rc == 2
    # Backend wasn't called.
    assert [c for c in captured_backend if c["op"] == "create"] == []


def test_list_input_docs(captured_backend, capsys):
    rc = main(["list-input-docs", "--project-id", "proj_1"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert len(parsed["input_documents"]) == 1
    assert parsed["input_documents"][0]["id"] == "doc_A"
    list_calls = [c for c in captured_backend if c["op"] == "list"]
    assert list_calls == [{"op": "list", "project_id": "proj_1"}]
