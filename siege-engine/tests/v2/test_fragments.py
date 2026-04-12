"""Tests for backend.graph.fragments — the fragment ID format."""

from __future__ import annotations

import pytest

from backend.graph.fragments import (
    FragmentKind,
    InvalidFragmentIdError,
    fragment_id,
    parse_fragment_id,
)


class TestFragmentKind:
    def test_vocabulary(self):
        assert {k.value for k in FragmentKind} == {
            "techspec",
            "pubapi",
            "privapi",
            "deps",
        }

    def test_all_kinds_are_single_token(self):
        # The parser splits on the last underscore, so any fragment
        # kind containing "_" would corrupt owner-ID parsing. The
        # module-level assert in backend.graph.fragments catches this
        # at import time; this test is a second line of defense.
        for kind in FragmentKind:
            assert "_" not in kind.value


class TestFragmentIdBuild:
    @pytest.mark.parametrize("kind", list(FragmentKind))
    def test_build_roundtrips(self, kind):
        owner = "comp_ABCDEFGH"
        fid = fragment_id(owner, kind)
        assert fid == f"{owner}_{kind.value}"
        parsed_owner, parsed_kind = parse_fragment_id(fid)
        assert parsed_owner == owner
        assert parsed_kind == kind

    def test_rejects_malformed_owner(self):
        from backend.graph.ids import InvalidIdError

        with pytest.raises(InvalidIdError):
            fragment_id("garbage", FragmentKind.PUBAPI)


class TestParseFragmentId:
    def test_last_underscore_split(self):
        # Owner IDs contain an underscore, so splitting on the *first*
        # underscore would return the wrong owner.
        owner, kind = parse_fragment_id("comp_ABCDEFGH_pubapi")
        assert owner == "comp_ABCDEFGH"
        assert kind == FragmentKind.PUBAPI

    def test_rejects_non_string(self):
        with pytest.raises(InvalidFragmentIdError, match="must be a string"):
            parse_fragment_id(42)  # type: ignore[arg-type]

    def test_rejects_missing_underscore(self):
        with pytest.raises(InvalidFragmentIdError):
            parse_fragment_id("nosep")

    def test_rejects_unknown_kind(self):
        with pytest.raises(InvalidFragmentIdError, match="Unknown fragment kind"):
            parse_fragment_id("comp_ABCDEFGH_notakind")

    def test_rejects_malformed_owner(self):
        with pytest.raises(InvalidFragmentIdError, match="Invalid owner ID"):
            parse_fragment_id("garbage_pubapi")

    def test_all_kinds_parseable(self):
        for kind in FragmentKind:
            owner, parsed_kind = parse_fragment_id(f"comp_ABCDEFGH_{kind.value}")
            assert owner == "comp_ABCDEFGH"
            assert parsed_kind == kind
