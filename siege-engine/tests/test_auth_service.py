"""Tests for backend.auth.service – password hashing and JWT tokens."""

from datetime import datetime, timedelta

import pytest
from jose import jwt

from backend.auth.service import create_token, decode_token, hash_password, verify_password
from backend.config import settings

# ── Password hashing ──────────────────────────────────────────────


class TestHashPassword:
    def test_returns_bcrypt_hash(self):
        hashed = hash_password("secret123")
        assert hashed.startswith("$2")
        assert hashed != "secret123"

    def test_different_calls_produce_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # different salts

    def test_truncates_at_72_bytes(self):
        long_pw = "a" * 100
        hashed = hash_password(long_pw)
        # Should still produce a valid hash
        assert verify_password(long_pw, hashed)


class TestVerifyPassword:
    def test_correct_password(self):
        hashed = hash_password("correct")
        assert verify_password("correct", hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False


# ── JWT tokens ─────────────────────────────────────────────────────


class TestCreateToken:
    def test_creates_valid_jwt(self):
        token = create_token("user-1", "alice")
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["sub"] == "user-1"
        assert payload["username"] == "alice"
        assert "exp" in payload
        assert "iat" in payload

    def test_token_contains_expiry(self):
        token = create_token("u1", "bob")
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        exp = datetime.utcfromtimestamp(payload["exp"])
        now = datetime.utcnow()
        # Expiry should be roughly jwt_expiry_hours from now
        assert exp > now
        assert exp < now + timedelta(hours=settings.jwt_expiry_hours + 1)


class TestDecodeToken:
    def test_decodes_valid_token(self):
        token = create_token("user-2", "carol")
        payload = decode_token(token)
        assert payload["sub"] == "user-2"
        assert payload["username"] == "carol"

    def test_expired_token_raises(self):
        payload = {
            "sub": "user-3",
            "username": "dave",
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=2),
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(Exception):
            decode_token(token)

    def test_invalid_token_raises(self):
        with pytest.raises(Exception):
            decode_token("not-a-valid-token")

    def test_wrong_secret_raises(self):
        token = jwt.encode(
            {"sub": "x", "username": "y", "exp": datetime.utcnow() + timedelta(hours=1)},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(Exception):
            decode_token(token)
