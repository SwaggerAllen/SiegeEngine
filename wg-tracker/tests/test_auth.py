import pytest

from wgtracker.models import UserRole
from wgtracker.web import auth


def test_first_user_becomes_admin(session):
    assert auth.needs_bootstrap(session)
    user = auth.create_admin_bootstrap(session, "admin@x.com", "password123")
    assert user.role == UserRole.admin
    assert not auth.needs_bootstrap(session)


def test_bootstrap_refused_after_first(session):
    auth.create_admin_bootstrap(session, "admin@x.com", "password123")
    with pytest.raises(auth.AuthError):
        auth.create_admin_bootstrap(session, "second@x.com", "password123")


def test_password_too_short(session):
    with pytest.raises(auth.AuthError):
        auth.create_admin_bootstrap(session, "admin@x.com", "short")


def test_authenticate(session):
    auth.create_admin_bootstrap(session, "admin@x.com", "password123")
    assert auth.authenticate(session, "admin@x.com", "password123") is not None
    assert auth.authenticate(session, "admin@x.com", "wrong") is None
    assert auth.authenticate(session, "nobody@x.com", "password123") is None


def test_invite_lifecycle_and_viewer_role(session):
    admin = auth.create_admin_bootstrap(session, "admin@x.com", "password123")
    invite = auth.create_invite(session, created_by=admin.id, note="for alice")
    assert auth.invite_is_valid(invite)

    viewer = auth.register_from_invite(session, invite.token, "alice@x.com", "password123")
    assert viewer.role == UserRole.viewer

    # Single-use: token can't be reused.
    assert not auth.invite_is_valid(auth.get_invite(session, invite.token))
    with pytest.raises(auth.AuthError):
        auth.register_from_invite(session, invite.token, "eve@x.com", "password123")


def test_revoked_invite_rejected(session):
    admin = auth.create_admin_bootstrap(session, "admin@x.com", "password123")
    invite = auth.create_invite(session, created_by=admin.id)
    auth.revoke_invite(session, invite.token)
    with pytest.raises(auth.AuthError):
        auth.register_from_invite(session, invite.token, "alice@x.com", "password123")


def test_expired_invite_rejected(session):
    admin = auth.create_admin_bootstrap(session, "admin@x.com", "password123")
    invite = auth.create_invite(session, created_by=admin.id, expires_in_days=-1)
    assert not auth.invite_is_valid(invite)
