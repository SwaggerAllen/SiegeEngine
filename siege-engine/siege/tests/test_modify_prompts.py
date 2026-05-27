"""Tests for the ``get-context --prompt-variant modify`` pathway.

The modify prompts (``siege/prompts/modify_<tier>.md``) swap the
``instructions`` field of the generation context bundle so a skill
running ``modify-<tier>`` gets the surgical-edit framing without
changing any other part of the per-tier context.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from siege.cli import main
from siege.prompts import load_generation_prompt


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    (path / "README").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def test_modify_sysarch_prompt_exists():
    """The three new modify prompts must be loadable through the same
    helper the CLI uses — `load_generation_prompt` falls back to empty
    on a missing tier, so a successful non-empty load is the contract."""
    for tier in ("sysarch", "comparch", "subcomparch"):
        text = load_generation_prompt(f"modify_{tier}")
        assert text, f"missing modify prompt for tier {tier}"
        # Spot-check that the modify framing made it in.
        assert "surgical" in text.lower() or "preserve" in text.lower()


def test_get_context_modify_variant_swaps_instructions(tmp_path, capsys):
    """``get-context --prompt-variant modify`` returns the modify
    prompt in the bundle's ``instructions`` field, not the regen one.
    The rest of the bundle is unchanged."""
    repo = _git_repo(tmp_path)
    # Seed a feature_expansion + requirements + sysarch substrate so
    # get-context sysarch has something to project.
    body_fe = "<features>\n  <feature><name>Login</name><intent>i</intent></feature>\n</features>\n"
    (repo / "feature_expansion" / "proj").mkdir(parents=True)
    (repo / "feature_expansion" / "proj" / "body.md").write_text(body_fe)
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
    (repo / "requirements" / "proj").mkdir(parents=True)
    (repo / "requirements" / "proj" / "body.md").write_text(
        "<requirements>\n"
        "  <responsibility><name>Auth</name><feats/></responsibility>\n"
        "</requirements>\n"
    )
    main(
        [
            "write-draft",
            "--repo",
            str(repo),
            "--tier",
            "requirements",
            "--comp-id",
            "proj",
            "--body-path",
            "requirements/proj/body.md",
        ]
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)

    # Default variant — the bundle's instructions field carries the
    # standard sysarch prompt.
    capsys.readouterr()
    rc = main(["get-context", "--repo", str(repo), "--tier", "sysarch", "--comp-id", "proj"])
    assert rc == 0
    default_bundle = json.loads(capsys.readouterr().out)
    assert default_bundle.get("prompt_variant") is None
    default_instructions = default_bundle["instructions"]
    assert default_instructions
    # The default sysarch prompt mentions "system architecture" early
    # on; the modify variant uses "surgical modification" framing.
    assert "surgical" not in default_instructions.lower()

    # Modify variant — instructions swap, prompt_variant marker is set.
    rc = main(
        [
            "get-context",
            "--repo",
            str(repo),
            "--tier",
            "sysarch",
            "--comp-id",
            "proj",
            "--prompt-variant",
            "modify",
        ]
    )
    assert rc == 0
    modify_bundle = json.loads(capsys.readouterr().out)
    assert modify_bundle["prompt_variant"] == "modify"
    assert modify_bundle["instructions"] != default_instructions
    assert "surgical" in modify_bundle["instructions"].lower()
    # Every other key in the bundle is unchanged.
    for key, value in default_bundle.items():
        if key in ("instructions", "prompt_variant"):
            continue
        assert modify_bundle.get(key) == value, (
            f"bundle key {key!r} drifted under --prompt-variant modify"
        )
