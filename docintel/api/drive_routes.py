from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, localfolder, sync
from ..drive import GoogleDrive, parse_folder_ref
from ..models import DriveFile, GoogleAccount, WatchedFolder
from .deps import get_session

router = APIRouter(prefix="/api", tags=["drive"])


def _account(request: Request, session: Session) -> GoogleAccount:
    user = auth.require_user(request, session)
    acct = session.scalar(select(GoogleAccount).where(GoogleAccount.user_id == user.id))
    if acct is None:
        raise HTTPException(401, "no Google account linked")
    return acct


def _drive(session: Session, acct: GoogleAccount) -> GoogleDrive:
    try:
        return GoogleDrive(auth.credentials_for(session, acct))
    except auth.ReauthRequired as exc:
        raise HTTPException(401, f"Google access expired, reconnect: {exc}") from exc


@router.get("/drive/folders")
def folders(request: Request, q: str = "", session: Session = Depends(get_session)):
    acct = _account(request, session)
    return {"folders": _drive(session, acct).list_folders(q)}


class FolderIn(BaseModel):
    ref: str


@router.post("/folders")
def watch_folder(body: FolderIn, request: Request, session: Session = Depends(get_session)):
    acct = _account(request, session)
    try:
        folder_id = parse_folder_ref(body.ref)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    drive = _drive(session, acct)
    try:
        meta = drive.folder_meta(folder_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"folder not found or not shared with this account: {type(exc).__name__}") from exc
    if meta.get("mimeType") != "application/vnd.google-apps.folder":
        raise HTTPException(400, "that id is a file, not a folder")
    for f in session.scalars(select(WatchedFolder).where(WatchedFolder.google_account_id == acct.id)):
        f.active = f.folder_id == folder_id
    folder = session.scalar(select(WatchedFolder).where(WatchedFolder.google_account_id == acct.id, WatchedFolder.folder_id == folder_id))
    if folder is None:
        folder = WatchedFolder(google_account_id=acct.id, folder_id=folder_id, folder_name=meta.get("name", ""), active=True)
        session.add(folder)
    folder.folder_name = meta.get("name", "")
    session.commit()
    threading.Thread(target=sync.run_all_folders, daemon=True).start()
    return {"id": folder.id, "folder_id": folder.folder_id, "name": folder.folder_name}


@router.post("/sync")
def sync_now():
    return {"results": sync.run_all_folders()}


@router.get("/sync/status")
def sync_status(session: Session = Depends(get_session)):
    counts = {s: n for s, n in session.execute(select(DriveFile.status, func.count()).group_by(DriveFile.status))}
    from ..models import LocalFile
    for st, n in session.execute(select(LocalFile.status, func.count()).group_by(LocalFile.status)):
        counts[st] = counts.get(st, 0) + n
    folder = session.scalar(select(WatchedFolder).where(WatchedFolder.active.is_(True)))
    return {**sync.status(), "counts": counts, "local": localfolder.status(),
            "folder": {"name": folder.folder_name, "last_tick_at": folder.last_tick_at.isoformat(timespec="seconds") if folder.last_tick_at else None,
                       "last_tick_summary": folder.last_tick_summary} if folder else None}
