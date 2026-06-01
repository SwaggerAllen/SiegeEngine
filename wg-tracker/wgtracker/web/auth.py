"""Authentication primitives for the web UI.

- Passwords hashed with bcrypt.
- First registered account is promoted to admin automatically (bootstrap).
- Admins mint single-use, optionally-expiring invite tokens for viewer access.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Invite, User, UserRole

MIN_PASSWORD_LEN = 8


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    # bcrypt operates on at most 72 bytes; longer inputs are truncated by the algo.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def user_count(session: Session) -> int:
    return int(session.execute(select(func.count(User.id))).scalar_one())


def needs_bootstrap(session: Session) -> bool:
    """True when no users exist yet → the next registrant becomes admin."""
    return user_count(session) == 0


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(session, email)
    if user and verify_password(password, user.password_hash):
        return user
    return None


def _validate_credentials(email: str, password: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 3:
        raise AuthError("Enter a valid email address.")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    return email


def create_admin_bootstrap(session: Session, email: str, password: str) -> User:
    """Create the first user as admin. Refuses if any user already exists."""
    if not needs_bootstrap(session):
        raise AuthError("Setup already completed; an admin already exists.")
    email = _validate_credentials(email, password)
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole.admin,
        created_at=datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    return user


def get_invite(session: Session, token: str) -> Invite | None:
    return session.get(Invite, token)


def invite_is_valid(invite: Invite | None) -> bool:
    if invite is None or invite.revoked or invite.used_by is not None:
        return False
    if invite.expires_at is not None and invite.expires_at < datetime.now(UTC):
        return False
    return True


def create_invite(
    session: Session,
    *,
    created_by: int,
    role: UserRole = UserRole.viewer,
    expires_in_days: int | None = 14,
    note: str | None = None,
) -> Invite:
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days)
        if expires_in_days
        else None
    )
    invite = Invite(
        token=token,
        role=role,
        created_by=created_by,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
        note=note,
    )
    session.add(invite)
    session.flush()
    return invite


def revoke_invite(session: Session, token: str) -> None:
    invite = session.get(Invite, token)
    if invite is not None:
        invite.revoked = True
        session.flush()


def register_from_invite(session: Session, token: str, email: str, password: str) -> User:
    invite = get_invite(session, token)
    if not invite_is_valid(invite):
        raise AuthError("This invite link is invalid, expired, or already used.")
    assert invite is not None
    email = _validate_credentials(email, password)
    if get_user_by_email(session, email) is not None:
        raise AuthError("An account with that email already exists.")
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=invite.role,
        created_at=datetime.now(UTC),
        invite_token=token,
    )
    session.add(user)
    session.flush()
    invite.used_by = user.id
    invite.used_at = datetime.now(UTC)
    session.flush()
    return user


def list_invites(session: Session) -> list[Invite]:
    return list(
        session.execute(select(Invite).order_by(Invite.created_at.desc())).scalars().all()
    )
