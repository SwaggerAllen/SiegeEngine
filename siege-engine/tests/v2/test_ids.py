"""Tests for backend.graph.ids."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.graph.ids import (
    COLLISION_RETRIES,
    SUFFIX_LENGTH,
    IdCollisionError,
    InvalidIdError,
    Kind,
    mint,
    validate,
)
from backend.models.node import Node


class TestKindEnum:
    def test_all_kinds_present(self):
        assert {k.value for k in Kind} == {
            "feat",
            "resp",
            "comp",
            "impl",
            "plan",
            "policy",
            "edge",
            "expansion",
            "reqs",
            "subreqs",
            "sysarch",
            "manifest",
            "fanin",
            "vocab",
        }


class TestValidate:
    @pytest.mark.parametrize("kind", list(Kind))
    def test_valid_minted_id_roundtrips(self, kind, db):
        minted = mint(db, kind)
        parsed_kind, suffix = validate(minted)
        assert parsed_kind == kind
        assert len(suffix) == SUFFIX_LENGTH

    def test_rejects_non_string(self):
        with pytest.raises(InvalidIdError, match="must be a string"):
            validate(123)  # type: ignore[arg-type]

    def test_rejects_missing_underscore(self):
        with pytest.raises(InvalidIdError, match="missing underscore"):
            validate("comp")

    def test_rejects_unknown_kind(self):
        with pytest.raises(InvalidIdError, match="Unknown kind"):
            validate("xxxx_ABCDEFGH")

    def test_rejects_wrong_suffix_length(self):
        with pytest.raises(InvalidIdError, match="suffix must be"):
            validate("comp_ABC")

    def test_rejects_non_crockford_chars(self):
        # 'I' and 'L' are not in Crockford's alphabet
        with pytest.raises(InvalidIdError, match="non-Crockford"):
            validate("comp_ILILILIL")


class TestMint:
    def test_returns_valid_id(self, db):
        minted = mint(db, Kind.COMP)
        kind, _ = validate(minted)
        assert kind == Kind.COMP
        assert minted.startswith("comp_")

    def test_collision_retry_path(self, db, project):
        # Pre-populate a node with a known ID, then force mint() to
        # collide with it on the first try, then succeed.
        colliding_suffix = "AAAAAAAA"
        clean_suffix = "BBBBBBBB"
        colliding_id = f"comp_{colliding_suffix}"
        db.add(
            Node(
                id=colliding_id,
                project_id=project.id,
                tier="comp",
                kind="domain",
                name="existing",
            )
        )
        db.flush()

        with patch(
            "backend.graph.ids._random_suffix",
            side_effect=[colliding_suffix, clean_suffix],
        ):
            minted = mint(db, Kind.COMP)
        assert minted == f"comp_{clean_suffix}"

    def test_collision_exhaustion_raises(self, db, project):
        # Force every attempt to collide with an existing row.
        colliding_suffix = "CCCCCCCC"
        colliding_id = f"comp_{colliding_suffix}"
        db.add(
            Node(
                id=colliding_id,
                project_id=project.id,
                tier="comp",
                kind="domain",
                name="existing",
            )
        )
        db.flush()

        with patch(
            "backend.graph.ids._random_suffix",
            return_value=colliding_suffix,
        ):
            with pytest.raises(IdCollisionError, match="Failed to mint"):
                mint(db, Kind.COMP)

    def test_mint_exhaustion_count(self, db):
        # If we mock _random_suffix to always return a non-existent value,
        # mint() succeeds on the first try (no collision budget consumed).
        with patch(
            "backend.graph.ids._random_suffix",
            return_value="DDDDDDDD",
        ):
            # Should succeed on first try, not exhaust retries.
            assert mint(db, Kind.FEAT) == "feat_DDDDDDDD"

    def test_retries_are_bounded(self):
        assert COLLISION_RETRIES >= 1
