import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from backend.auth import service as auth_service
from backend.auth.schemas import (
    InviteResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.database import get_db
from backend.models import InviteLink, User

router = APIRouter()
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = auth_service.decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    return user


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def _user_response(user: User, token: str) -> dict:
    return {
        "token": token,
        "user": {"id": user.id, "username": user.username, "role": user.role},
    }


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    user_count = db.query(User).count()
    is_first_user = user_count == 0

    if not is_first_user:
        # Require a valid invite token
        if not req.invite_token:
            raise HTTPException(400, "Invite token required for registration")
        invite = (
            db.query(InviteLink)
            .filter_by(token=req.invite_token, used=False)
            .first()
        )
        if not invite:
            raise HTTPException(400, "Invalid invite token")
        if invite.expires_at < datetime.utcnow():
            raise HTTPException(400, "Invite token has expired")
    else:
        invite = None

    # Check username uniqueness
    if db.query(User).filter_by(username=req.username).first():
        raise HTTPException(409, "Username already taken")

    user = User(
        username=req.username,
        password_hash=auth_service.hash_password(req.password),
        role="admin" if is_first_user else "member",
        invited_by=invite.created_by if invite else None,
    )
    db.add(user)

    if invite:
        invite.used = True
        invite.used_by = user.id

    db.commit()
    db.refresh(user)
    token = auth_service.create_token(user.id, user.username)
    return _user_response(user, token)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=req.username).first()
    if not user or not auth_service.verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = auth_service.create_token(user.id, user.username)
    return _user_response(user, token)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """Check if any user has been registered (for first-run detection)."""
    has_user = db.query(User).count() > 0
    return {"has_user": has_user}


# ──── Invite Management (Admin Only) ────


@router.post("/invites", response_model=InviteResponse)
def create_invite(
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=24)
    invite = InviteLink(
        token=token,
        created_by=user.id,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return {
        "id": invite.id,
        "token": invite.token,
        "url": f"/login?invite={invite.token}",
        "expires_at": invite.expires_at.isoformat(),
        "used": invite.used,
        "created_at": invite.created_at.isoformat(),
    }


@router.get("/invites")
def list_invites(
    db: Session = Depends(get_db),
    _user: User = Depends(_require_admin),
):
    invites = (
        db.query(InviteLink)
        .filter_by(used=False)
        .filter(InviteLink.expires_at > datetime.utcnow())
        .order_by(InviteLink.created_at.desc())
        .all()
    )
    return [
        {
            "id": inv.id,
            "token": inv.token,
            "url": f"/login?invite={inv.token}",
            "expires_at": inv.expires_at.isoformat(),
            "used": inv.used,
            "created_at": inv.created_at.isoformat(),
        }
        for inv in invites
    ]


@router.delete("/invites/{invite_id}")
def revoke_invite(
    invite_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_admin),
):
    invite = db.get(InviteLink, invite_id)
    if not invite:
        raise HTTPException(404, "Invite not found")
    db.delete(invite)
    db.commit()
    return {"status": "revoked"}


@router.get("/invite/{token}")
def validate_invite(token: str, db: Session = Depends(get_db)):
    """Public endpoint to validate an invite token."""
    invite = db.query(InviteLink).filter_by(token=token, used=False).first()
    if not invite:
        return {"valid": False}
    if invite.expires_at < datetime.utcnow():
        return {"valid": False}
    return {"valid": True, "expires_at": invite.expires_at.isoformat()}
