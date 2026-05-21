"""Smoke tests for the siege substrate.

Cover the round-trip paths that absolutely must work for any further
development — state JSON parse/dump, body section parsing, fragment
section names, review XML parse. Real per-tier tests come later with
a real git fixture.
"""

from __future__ import annotations

import json

from siege import fragments, validate


def test_state_round_trip():
    from siege.state import Scope, State, dump_state, parse_state

    s = State(
        schema_version=1,
        scope=Scope(tier="comparch", comp_id="comp_a"),
        status="drafted",
        nonce="01HX",
        is_foundation=True,
        edges={"dependencies": ["comp_b", "comp_c"]},
        meta={"name": "Alpha", "kind": "service"},
    )
    payload = dump_state(s)
    re = parse_state(json.loads(json.dumps(payload)))
    assert re.scope.comp_id == "comp_a"
    assert re.is_foundation
    assert re.edges["dependencies"] == ["comp_b", "comp_c"]
    assert re.meta["kind"] == "service"


def test_body_section_parse():
    body = """## comparch:techspec
some techspec content
spanning lines

## comparch:pubapi
api content

## sub:sub_xyz:techspec
sub seed content
"""
    sections = fragments.parse_body_sections(body)
    assert "comparch:techspec" in sections
    assert "spanning lines" in sections["comparch:techspec"]
    assert sections["comparch:pubapi"].startswith("api content")
    assert "sub:sub_xyz:techspec" in sections


def test_section_for_kind():
    assert (
        fragments.section_for_kind(fragments.FragmentKind.COMPARCH_TECHSPEC) == "comparch:techspec"
    )
    assert (
        fragments.section_for_kind(fragments.FragmentKind.TECHSPEC, sub_id="sub_a")
        == "sub:sub_a:techspec"
    )


def test_validate_empty_body():
    out = validate.validate_artifact(tier="comparch", body="")
    assert out["ok"] is False
    assert "empty" in out["errors"][0]


def test_validate_missing_section_warns():
    body = "## comparch:techspec\ncontent\n"
    out = validate.validate_artifact(tier="comparch", body=body)
    assert out["ok"] is True
    assert any("comparch:pubapi" in w for w in out["warnings"])


def test_review_xml_parse():
    from siege.parsers.review_xml import parse_review

    raw = """
    <review>
      <intro>Overall solid, a couple of structural issues.</intro>
      <score>72</score>
      <handles-structure>
        <finding id="h1">handle inconsistency in section X</finding>
      </handles-structure>
      <architectural-decisions>
        <finding id="a1">policy attribution unclear</finding>
      </architectural-decisions>
    </review>
    """
    parsed = parse_review(raw)
    assert parsed.score == 72
    assert len(parsed.handles_structure) == 1
    assert parsed.architectural_decisions[0].id == "a1"


def test_fragment_layer_lookup():
    from siege.fragments import (
        COMPARCH_LAYER_FALLBACK,
        LAYERED_KIND_FOR_TOP_LEVEL,
        FragmentKind,
    )

    assert COMPARCH_LAYER_FALLBACK[FragmentKind.COMPARCH_TECHSPEC] == FragmentKind.TECHSPEC
    assert LAYERED_KIND_FOR_TOP_LEVEL[FragmentKind.PUBAPI] == FragmentKind.COMPARCH_PUBAPI


def test_scope_paths():
    from siege.state import Scope

    top = Scope(tier="comparch", comp_id="comp_a")
    assert top.state_path() == "state/comparch/comp_a.json"
    assert top.body_path() == "comparch/comp_a/body.md"

    sub = Scope(tier="subcomparch", parent_id="comp_a", sub_id="sub_x")
    assert sub.state_path() == "state/subcomparch/comp_a/sub_x.json"
    assert sub.body_path() == "subcomparch/comp_a/subs/sub_x/body.md"
