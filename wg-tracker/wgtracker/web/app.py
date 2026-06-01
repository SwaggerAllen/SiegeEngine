"""FastAPI web application: authenticated, server-rendered browse UI.

Auth model (spec addendum):
  - /setup is available only until the first account exists; that account is admin.
  - /login + cookie session for everyone.
  - admins mint invite links at /admin granting read-only "viewer" accounts.
  - all archive views require login; invite management requires admin.
Also exposes /healthz for the App Platform health check.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from .. import queries
from ..config import get_settings
from ..db import session_scope
from ..logging_conf import configure_logging
from ..models import User, UserRole
from . import auth

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="WG Activity Tracker")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="wgt_session",
        https_only=False,  # App Platform terminates TLS upstream
        same_site="lax",
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # ----------------------------------------------------------------- helpers
    def current_user(request: Request) -> User | None:
        uid = request.session.get("uid")
        if uid is None:
            return None
        with session_scope() as s:
            return s.get(User, uid)

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        user = ctx.pop("user", None) or current_user(request)
        ctx.setdefault("topics", [t.name for t in settings.topics])
        ctx.setdefault("working_groups", [w.name for w in settings.working_groups])
        return templates.TemplateResponse(
            request, name, {"user": user, **ctx}
        )

    def require_login(request: Request) -> User | RedirectResponse:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return user

    # ------------------------------------------------------------------ health
    @app.get("/healthz")
    def healthz() -> dict:
        try:
            with session_scope() as s:
                s.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok}

    # -------------------------------------------------------------------- root
    @app.get("/")
    def index(request: Request):
        with session_scope() as s:
            if auth.needs_bootstrap(s):
                return RedirectResponse("/setup", status_code=303)
        if current_user(request) is None:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/threads", status_code=303)

    # ------------------------------------------------------------------- setup
    @app.get("/setup", response_class=HTMLResponse)
    def setup_form(request: Request):
        with session_scope() as s:
            if not auth.needs_bootstrap(s):
                return RedirectResponse("/login", status_code=303)
        return render(request, "setup.html", error=None)

    @app.post("/setup")
    def setup_submit(request: Request, email: str = Form(...), password: str = Form(...)):
        with session_scope() as s:
            try:
                user = auth.create_admin_bootstrap(s, email, password)
            except auth.AuthError as exc:
                return render(request, "setup.html", error=str(exc))
            uid = user.id
        request.session["uid"] = uid
        return RedirectResponse("/threads", status_code=303)

    # ------------------------------------------------------------------- login
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        with session_scope() as s:
            if auth.needs_bootstrap(s):
                return RedirectResponse("/setup", status_code=303)
        return render(request, "login.html", error=None)

    @app.post("/login")
    def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
        with session_scope() as s:
            user = auth.authenticate(s, email, password)
            uid = user.id if user else None
        if uid is None:
            return render(request, "login.html", error="Invalid email or password.")
        request.session["uid"] = uid
        return RedirectResponse("/threads", status_code=303)

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # ------------------------------------------------------------ invite accept
    @app.get("/invite/{token}", response_class=HTMLResponse)
    def invite_form(request: Request, token: str):
        with session_scope() as s:
            invite = auth.get_invite(s, token)
            valid = auth.invite_is_valid(invite)
        return render(request, "register.html", token=token, valid=valid, error=None)

    @app.post("/invite/{token}")
    def invite_submit(
        request: Request, token: str, email: str = Form(...), password: str = Form(...)
    ):
        with session_scope() as s:
            try:
                user = auth.register_from_invite(s, token, email, password)
            except auth.AuthError as exc:
                invite = auth.get_invite(s, token)
                return render(
                    request,
                    "register.html",
                    token=token,
                    valid=auth.invite_is_valid(invite),
                    error=str(exc),
                )
            uid = user.id
        request.session["uid"] = uid
        return RedirectResponse("/threads", status_code=303)

    # ------------------------------------------------------------------- admin
    @app.get("/admin", response_class=HTMLResponse)
    def admin_page(request: Request):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        if user.role != UserRole.admin:
            return render(request, "forbidden.html", user=user)
        with session_scope() as s:
            invites = auth.list_invites(s)
            rows = [
                {
                    "token": i.token,
                    "role": i.role.value,
                    "created_at": i.created_at.isoformat(timespec="minutes"),
                    "expires_at": i.expires_at.isoformat(timespec="minutes") if i.expires_at else None,
                    "note": i.note,
                    "used": i.used_by is not None,
                    "revoked": i.revoked,
                    "valid": auth.invite_is_valid(i),
                    "url": f"{settings.public_base_url}/invite/{i.token}",
                }
                for i in invites
            ]
        return render(request, "admin.html", user=user, invites=rows, created_url=None)

    @app.post("/admin/invites")
    def create_invite_route(
        request: Request,
        note: str = Form(""),
        expires_in_days: int = Form(14),
    ):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        if user.role != UserRole.admin:
            return render(request, "forbidden.html", user=user)
        with session_scope() as s:
            invite = auth.create_invite(
                s,
                created_by=user.id,
                role=UserRole.viewer,
                expires_in_days=expires_in_days or None,
                note=note or None,
            )
            url = f"{settings.public_base_url}/invite/{invite.token}"
            invites = auth.list_invites(s)
            rows = [
                {
                    "token": i.token,
                    "role": i.role.value,
                    "created_at": i.created_at.isoformat(timespec="minutes"),
                    "expires_at": i.expires_at.isoformat(timespec="minutes") if i.expires_at else None,
                    "note": i.note,
                    "used": i.used_by is not None,
                    "revoked": i.revoked,
                    "valid": auth.invite_is_valid(i),
                    "url": f"{settings.public_base_url}/invite/{i.token}",
                }
                for i in invites
            ]
        return render(request, "admin.html", user=user, invites=rows, created_url=url)

    @app.post("/admin/invites/{token}/revoke")
    def revoke_invite_route(request: Request, token: str):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        if user.role != UserRole.admin:
            return render(request, "forbidden.html", user=user)
        with session_scope() as s:
            auth.revoke_invite(s, token)
        return RedirectResponse("/admin", status_code=303)

    # ----------------------------------------------------------------- browse
    def _parse_date(value: str | None):
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    @app.get("/threads", response_class=HTMLResponse)
    def threads_page(
        request: Request,
        topic: str | None = None,
        working_group: str | None = None,
        since: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        with session_scope() as s:
            if q:
                rows = queries.search_threads_fts(s, q)
            else:
                rows = queries.list_threads(
                    s,
                    topic=topic or None,
                    working_group=working_group or None,
                    since=_parse_date(since),
                    status=status or None,
                )
        return render(
            request,
            "threads.html",
            user=user,
            rows=rows,
            filters={"topic": topic, "working_group": working_group, "since": since, "status": status, "q": q},
        )

    @app.get("/threads/{thread_id}", response_class=HTMLResponse)
    def thread_detail_page(request: Request, thread_id: str):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        with session_scope() as s:
            detail = queries.get_thread_detail(s, thread_id)
        if detail is None:
            return render(request, "notfound.html", user=user, what=f"thread {thread_id}")
        return render(request, "thread_detail.html", user=user, t=detail)

    @app.get("/drafts", response_class=HTMLResponse)
    def drafts_page(
        request: Request, topic: str | None = None, working_group: str | None = None
    ):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        with session_scope() as s:
            rows = queries.list_drafts(s, topic=topic or None, working_group=working_group or None)
        return render(
            request, "drafts.html", user=user, rows=rows,
            filters={"topic": topic, "working_group": working_group},
        )

    @app.get("/drafts/{draft_name}", response_class=HTMLResponse)
    def draft_detail_page(request: Request, draft_name: str):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        with session_scope() as s:
            detail = queries.get_draft(s, draft_name)
        if detail is None:
            return render(request, "notfound.html", user=user, what=f"draft {draft_name}")
        return render(request, "draft_detail.html", user=user, d=detail)

    @app.get("/topics/{topic}", response_class=HTMLResponse)
    def topic_page(request: Request, topic: str, working_group: str | None = None):
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
        with session_scope() as s:
            overview = queries.topic_overview(s, topic=topic, working_group=working_group or None)
        return render(request, "topic.html", user=user, o=overview)

    return app


app = create_app()
