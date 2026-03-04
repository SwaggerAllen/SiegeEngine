import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.config import settings
from backend.database import get_db
from backend.models import GitHubCredential, User

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

# In-memory state store for CSRF protection (keyed by user_id)
# Each entry: {"state": str, "created_at": float}
_oauth_states: dict[str, dict] = {}
_STATE_TTL = 600  # 10 minutes


def _cleanup_expired_states():
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - v["created_at"] > _STATE_TTL]
    for k in expired:
        del _oauth_states[k]


@router.get("/authorize")
def github_authorize(user: User = Depends(get_current_user)):
    """Returns the URL to redirect the user to for GitHub OAuth consent."""
    if not settings.github_client_id:
        raise HTTPException(400, "GitHub OAuth not configured")

    _cleanup_expired_states()

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)
    _oauth_states[user.id] = {"state": state, "created_at": time.time()}

    url = (
        f"{GITHUB_AUTHORIZE_URL}"
        f"?client_id={settings.github_client_id}"
        f"&scope=repo"
        f"&state={state}"
    )
    return {"authorize_url": url}


class GitHubConnectRequest(BaseModel):
    code: str
    state: str


@router.post("/connect")
async def github_connect(
    req: GitHubConnectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Exchange OAuth code for access token (called by authenticated SPA after redirect)."""
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(400, "GitHub OAuth not configured")

    # Validate CSRF state
    stored = _oauth_states.pop(user.id, None)
    if not stored or stored["state"] != req.state:
        raise HTTPException(400, "Invalid or expired OAuth state")
    if time.time() - stored["created_at"] > _STATE_TTL:
        raise HTTPException(400, "OAuth state expired")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": req.code,
            },
        )
        data = resp.json()

    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(400, f"GitHub OAuth failed: {data.get('error_description', 'unknown')}")

    # Get GitHub username
    from backend.github.service import GitHubService
    gh = GitHubService(access_token)
    gh_user = await gh.get_user()

    # Upsert credential
    existing = db.query(GitHubCredential).filter_by(user_id=user.id).first()
    if existing:
        existing.access_token = access_token
        existing.github_username = gh_user.get("login")
    else:
        cred = GitHubCredential(
            user_id=user.id,
            access_token=access_token,
            github_username=gh_user.get("login"),
        )
        db.add(cred)
    db.commit()

    return {"status": "connected", "github_username": gh_user.get("login")}


@router.get("/status")
def github_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if user has linked GitHub."""
    cred = db.query(GitHubCredential).filter_by(user_id=user.id).first()
    if cred:
        return {
            "connected": True,
            "github_username": cred.github_username,
        }
    return {"connected": False}
