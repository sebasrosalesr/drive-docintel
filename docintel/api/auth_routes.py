from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..models import Document, DriveFile, GoogleAccount, User, WatchedFolder
from .deps import get_session

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, response: Response):
    if not settings.app_password:
        return {"ok": True, "auth_required": False}
    if not secrets.compare_digest(body.password, settings.app_password):
        raise HTTPException(401, "wrong password")
    auth.set_app_auth(response)
    return {"ok": True, "auth_required": True}


@router.get("/me")
def me(request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request, session)
    out = {"signed_in": user is not None, "google_ready": settings.google_ready, "llm_ready": settings.llm_ready,
           "auth_required": bool(settings.app_password), "authed": auth.app_authed(request),
           "model": settings.model, "model_b": settings.fallback_model, "ask_model": settings.ask_model, "watch_dir": str(settings.watch_dir) if settings.watch_dir else None, "email": "", "name": "", "reauth_required": False, "folder": None}
    if user:
        out.update({"email": user.email, "name": user.name})
        acct = session.scalar(select(GoogleAccount).where(GoogleAccount.user_id == user.id))
        if acct:
            out["reauth_required"] = acct.reauth_required
            folder = session.scalar(select(WatchedFolder).where(WatchedFolder.google_account_id == acct.id, WatchedFolder.active.is_(True)))
            if folder:
                out["folder"] = {"id": folder.id, "folder_id": folder.folder_id, "name": folder.folder_name,
                                 "last_tick_at": folder.last_tick_at.isoformat(timespec="seconds") if folder.last_tick_at else None,
                                 "last_tick_summary": folder.last_tick_summary}
    return out


@router.get("/auth/google/start")
def google_start():
    url, state, verifier = auth.authorization_url()
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(auth.STATE_COOKIE, auth.pack_state(state, verifier), max_age=auth.STATE_MAX_AGE, httponly=True, samesite="lax", secure=not settings.is_local)
    return resp


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = "", session: Session = Depends(get_session)):
    if error:
        raise HTTPException(400, f"Google returned: {error}")
    packed = auth.unpack_state(request.cookies.get(auth.STATE_COOKIE))
    if not code or not state or not packed or not secrets.compare_digest(state, packed[0]):
        raise HTTPException(400, "OAuth state mismatch; start again")
    creds = auth.exchange_code(code, packed[1])
    info = auth.userinfo(creds)
    email = (info.get("email") or "").lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=info.get("name") or "")
        session.add(user)
        session.flush()
    acct = session.scalar(select(GoogleAccount).where(GoogleAccount.google_sub == info["sub"]))
    if acct is None:
        acct = GoogleAccount(user_id=user.id, google_sub=info["sub"], email=email)
        session.add(acct)
    if creds.refresh_token:
        acct.refresh_token_enc = auth.encrypt(creds.refresh_token)
    acct.scopes = " ".join(creds.scopes or [])
    acct.reauth_required = not bool(acct.refresh_token_enc)
    session.commit()
    resp = RedirectResponse("/", status_code=302)
    auth.set_session(resp, user.id)
    resp.delete_cookie(auth.STATE_COOKIE)
    return resp


@router.post("/auth/google/disconnect")
def google_disconnect(request: Request, session: Session = Depends(get_session)):
    """Disconnect Drive: the account and its encrypted refresh token go, its
    watched folders and their file rows go, and the session ends. Documents
    already read stay in the library, no longer tied to a Drive file."""
    user = auth.require_user(request, session)
    accounts = session.scalars(select(GoogleAccount).where(GoogleAccount.user_id == user.id)).all()
    folders = session.scalars(select(WatchedFolder).where(WatchedFolder.google_account_id.in_([a.id for a in accounts]))).all() if accounts else []
    # No ORM relationships are declared, so the flushes order the deletes by hand: files, folders, accounts, user.
    for folder in folders:
        for df in session.scalars(select(DriveFile).where(DriveFile.watched_folder_id == folder.id)):
            for doc in session.scalars(select(Document).where(Document.drive_file_id == df.id)):
                doc.drive_file_id = None
            session.delete(df)
        session.flush()
        session.delete(folder)
    session.flush()
    for account in accounts:
        session.delete(account)
    session.flush()
    session.delete(user)
    session.commit()
    resp = JSONResponse({"ok": True, "folders": len(folders)})
    auth.clear_session(resp)
    return resp


@router.post("/auth/logout")
def logout(response: Response):
    auth.clear_session(response)
    return {"ok": True}
