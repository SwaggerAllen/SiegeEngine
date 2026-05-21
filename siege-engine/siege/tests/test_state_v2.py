"""Schema v2 / phasing tests for siege.state.

Covers the `Scope.phase` dimension added for impl-tier phasing:
v1↔v2 parse tolerance, phased path layout, the `key()` 5-tuple
(load-bearing — a 4-tuple would collide phased impl nodes), and
round-trip stability.
"""

from __future__ import annotations

import json

from siege.state import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Scope,
    State,
    dump_state,
    parse_state,
)


def _v1_comparch_raw() -> dict:
    return {
        "schema_version": 1,
        "scope": {"tier": "comparch", "comp_id": "comp_a"},
        "status": "drafted",
        "nonce": "01HX",
        "draft": {
            "body_path": "comparch/comp_a/body.md",
            "body_sha256": "a" * 64,
            "generated_at": "2026-05-19T00:00:00Z",
        },
    }


def test_schema_version_is_2():
    assert SCHEMA_VERSION == 2
    assert SUPPORTED_SCHEMA_VERSIONS == frozenset({1, 2})


def test_v1_file_still_parses():
    """Existing v1 state files (every arch tier, pre-phasing impl)
    must keep parsing — forward compat, no migration."""
    state = parse_state(_v1_comparch_raw())
    assert state.schema_version == 1
    assert state.scope.tier == "comparch"
    assert state.scope.phase is None


def test_v1_redump_stays_v1():
    """dump_state must source schema_version from the State, not
    hard-code 2 — re-dumping a v1 file keeps it v1."""
    state = parse_state(_v1_comparch_raw())
    assert dump_state(state)["schema_version"] == 1


def test_v2_phased_impl_parses():
    raw = {
        "schema_version": 2,
        "scope": {
            "tier": "impl",
            "comp_id": None,
            "parent_id": "comp_a",
            "sub_id": "sub_x",
            "phase": 2,
        },
        "status": "drafted",
        "nonce": "01HX",
        "draft": {
            "body_path": "impl/comp_a/subs/sub_x/p2/body.md",
            "body_sha256": "b" * 64,
            "generated_at": "2026-05-19T00:00:00Z",
        },
    }
    state = parse_state(raw)
    assert state.schema_version == 2
    assert state.scope.phase == 2
    assert state.scope.parent_id == "comp_a"
    assert state.scope.sub_id == "sub_x"


def test_unsupported_version_rejected():
    raw = _v1_comparch_raw()
    raw["schema_version"] = 99
    try:
        parse_state(raw)
    except ValueError as exc:
        assert "99" in str(exc)
    else:
        raise AssertionError("expected ValueError for schema_version 99")


def test_phased_impl_paths():
    s = Scope(tier="impl", parent_id="comp_a", sub_id="sub_x", phase=2)
    assert s.state_path() == "state/impl/comp_a/p2/sub_x.json"
    assert s.body_path() == "impl/comp_a/subs/sub_x/p2/body.md"
    assert s.review_path() == "impl/comp_a/subs/sub_x/p2/review.md"


def test_phased_fanin_paths():
    s = Scope(tier="fanin", comp_id="comp_a", phase=3)
    assert s.state_path() == "state/fanin/comp_a/p3.json"
    assert s.body_path() == "fanin/comp_a/p3/body.md"
    assert s.review_path() == "fanin/comp_a/p3/review.md"


def test_unphased_paths_byte_identical_to_legacy():
    """phase=None must yield exactly the pre-phasing paths — no drift
    for any of the five arch tiers or a pre-phasing impl/fanin scope."""
    comparch = Scope(tier="comparch", comp_id="comp_a")
    assert comparch.state_path() == "state/comparch/comp_a.json"
    assert comparch.body_path() == "comparch/comp_a/body.md"

    subcomparch = Scope(tier="subcomparch", parent_id="comp_a", sub_id="sub_x")
    assert subcomparch.state_path() == "state/subcomparch/comp_a/sub_x.json"
    assert subcomparch.body_path() == "subcomparch/comp_a/subs/sub_x/body.md"

    # impl/fanin with phase=None keep the legacy layout too.
    legacy_impl = Scope(tier="impl", parent_id="comp_a", sub_id="sub_x")
    assert legacy_impl.state_path() == "state/impl/comp_a/sub_x.json"
    assert legacy_impl.body_path() == "impl/comp_a/subs/sub_x/body.md"

    legacy_fanin = Scope(tier="fanin", comp_id="comp_a")
    assert legacy_fanin.state_path() == "state/fanin/comp_a.json"
    assert legacy_fanin.body_path() == "fanin/comp_a/body.md"


def test_key_is_five_tuple_and_phase_distinguishes():
    """The load-bearing invariant: two phased impl nodes for the same
    subcomponent MUST produce distinct keys, or GitView._states drops
    one silently."""
    p1 = Scope(tier="impl", parent_id="comp_a", sub_id="sub_x", phase=1)
    p2 = Scope(tier="impl", parent_id="comp_a", sub_id="sub_x", phase=2)
    assert len(p1.key()) == 5
    assert p1.key() != p2.key()
    # An unphased scope's key is stable + distinct from any phased one.
    unphased = Scope(tier="impl", parent_id="comp_a", sub_id="sub_x")
    assert unphased.key() != p1.key()
    assert unphased.key()[4] == ""


def test_phase_round_trips_through_dump_parse():
    state = State(
        schema_version=2,
        scope=Scope(tier="impl", parent_id="comp_a", sub_id="sub_x", phase=2),
        status="drafted",
        nonce="01HX",
    )
    re = parse_state(json.loads(json.dumps(dump_state(state))))
    assert re.scope.phase == 2
    assert re.scope.key() == state.scope.key()
