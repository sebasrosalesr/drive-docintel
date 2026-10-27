"""Google sign-in + Drive consent in one OAuth web flow. The refresh token is stored encrypted.

Traps handled here (see README "Decisions"): redirect URI built from BASE_URL, token exchange by
`code=` with our own state check, relaxed scope comparison (Google renames/reorders scopes),
insecure-transport allowance only for http://localhost.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Response
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import settings
from .models import GoogleAccount, User

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.readonly",
]
SESSION_COOKIE = "docintel_session"
STATE_COOKIE = "docintel_oauth_state"
SESSION_MAX_AGE = 30 * 24 * 3600

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
if settings.is_local:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

_fernet = Fernet(settings.fernet_key)
_signer = URLSafeTimedSerializer(settings.app_secret, salt="session")


class ReauthRequired(Exception):
    pass


def redirect_uri() -> str:
    return settings.base_url + "/api/auth/google/callback"


def _flow() -> Flow:
    if not settings.google_ready:
        raise HTTPException(503, "Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")
    cfg = {"web": {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [redirect_uri()],
    }}
    return Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=redirect_uri())


def authorization_url() -> tuple[str, str]:
    return _flow().authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")


def exchange_code(code: str) -> Credentials:
    flow = _flow()
    flow.fetch_token(code=code)
    return flow.credentials


def userinfo(creds: Credentials) -> dict[str, Any]:
    r = httpx.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {creds.token}"}, timeout=20)
    r.raise_for_status()
    return r.json()


def encrypt(s: str) -> str:
    return _fernet.encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return _fernet.decrypt(s.encode()).decode()


def credentials_for(session: Session, account: GoogleAccount) -> Credentials:
    """Fresh access token from the stored refresh token. Flags the account when Google says no."""
    if not account.refresh_token_enc:
        account.reauth_required = True
        session.commit()
        raise ReauthRequired("no refresh token stored")
    creds = Credentials(
        None, refresh_token=decrypt(account.refresh_token_enc), token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id, client_secret=settings.google_client_secret, scopes=SCOPES,
    )
    try:
        creds.refresh(GoogleRequest())
    except RefreshError as exc:
        account.reauth_required = True
        session.commit()
        raise ReauthRequired(str(exc)) from exc
    if account.reauth_required:
        account.reauth_required = False
        session.commit()
    return creds


# ---------- session cookie ----------
def set_session(resp: Response, user_id: int) -> None:
    resp.set_cookie(SESSION_COOKIE, _signer.dumps({"uid": user_id}), max_age=SESSION_MAX_AGE, httponly=True,
                    samesite="lax", secure=not settings.is_local)


def clear_session(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE)


def session_user_id(request: Request) -> int | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return int(_signer.loads(raw, max_age=SESSION_MAX_AGE)["uid"])
    except (BadSignature, KeyError, ValueError):
        return None


def current_user(request: Request, session: Session) -> User | None:
    uid = session_user_id(request)
    return session.get(User, uid) if uid else None


def require_user(request: Request, session: Session) -> User:
    user = current_user(request, session)
    if user is None:
        raise HTTPException(401, "sign in with Google first")
    return user


# ---------- app password (optional, for a deployed demo) ----------
APP_COOKIE = "docintel_app"


def set_app_auth(resp: Response) -> None:
    resp.set_cookie(APP_COOKIE, _signer.dumps({"app": True}), max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=not settings.is_local)


def app_authed(request: Request) -> bool:
    if not settings.app_password:
        return True
    raw = request.cookies.get(APP_COOKIE)
    if not raw:
        return False
    try:
        return bool(_signer.loads(raw, max_age=SESSION_MAX_AGE).get("app"))
    except (BadSignature, ValueError):
        return False
