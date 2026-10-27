"""Watch the folder: diff Drive against drive_files every tick, extract what is new or changed.

Polling a recursive listing is enough at this scale (a few list calls per minute against a
325k-units/min quota). The upgrade path is Drive `changes.list` with a stored start token.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from . import auth
from .config import settings
from .db import SessionLocal
from .drive import DriveClient, GoogleDrive
from .models import Document, DriveFile, GoogleAccount, WatchedFolder, utcnow
from .pipeline import Unsupported, process_bytes
from .render import GOOGLE_DOC, GOOGLE_SHEET, kind_for

log = logging.getLogger("docintel.sync")
EXPORTS = {GOOGLE_DOC: ("application/pdf", ".pdf"), GOOGLE_SHEET: ("text/csv", ".csv")}
STALE_EXTRACTING = timedelta(minutes=15)

_pool = ThreadPoolExecutor(max_workers=max(1, settings.extract_concurrency), thread_name_prefix="extract")
_inflight: set[int] = set()
_inflight_lock = threading.Lock()
_tick_lock = threading.Lock()
_state: dict[str, Any] = {"last_tick_at": None, "next_tick_at": None, "last_error": "", "running": False}


def change_key(f: dict[str, Any]) -> str:
    """Binary files carry md5Checksum; Google-native files don't, so fall back to version+modifiedTime."""
    return f.get("md5Checksum") or f"v{f.get('version', '')}:{f.get('modifiedTime', '')}"


def local_key(df: DriveFile) -> str:
    return df.md5 or f"v{df.version}:{df.modified_time}"


def diff(remote: list[dict[str, Any]], local: dict[str, DriveFile]) -> dict[str, list]:
    """Pure: which remote files are new / changed / unchanged, and which local rows vanished."""
    new, changed, unchanged = [], [], []
    seen = set()
    for f in remote:
        fid = f["id"]
        seen.add(fid)
        df = local.get(fid)
        if df is None:
            new.append(f)
        elif local_key(df) != change_key(f) or df.status == "removed":
            changed.append(f)
        else:
            unchanged.append(f)
    removed = [df for fid, df in local.items() if fid not in seen and df.status != "removed"]
    return {"new": new, "changed": changed, "unchanged": unchanged, "removed": removed}


def _apply(session, folder: WatchedFolder, f: dict[str, Any], df: DriveFile | None) -> DriveFile:
    if df is None:
        df = DriveFile(watched_folder_id=folder.id, file_id=f["id"])
        session.add(df)
    df.name = f.get("name", "")
    df.mime = f.get("mimeType", "")
    df.md5 = f.get("md5Checksum", "") or ""
    df.version = str(f.get("version", "") or "")
    df.modified_time = f.get("modifiedTime", "") or ""
    df.size = int(f.get("size", 0) or 0)
    df.error = ""
    df.attempts = 0
    df.last_synced_at = utcnow()
    supported = kind_for(df.name, df.mime) != "unsupported" or df.mime in EXPORTS
    df.status = "pending" if supported else "skipped"
    if not supported:
        df.error = f"unsupported type: {df.mime or df.name}"
    return df


def tick(folder_db_id: int, *, drive: DriveClient | None = None, extract: bool = True) -> dict[str, Any]:
    """One sync pass for one watched folder. Returns counts. Extraction runs in the pool."""
    with SessionLocal() as session:
        folder = session.get(WatchedFolder, folder_db_id)
        if folder is None or not folder.active:
            return {"error": "folder not active"}
        if drive is None:
            account = session.get(GoogleAccount, folder.google_account_id)
            drive = GoogleDrive(auth.credentials_for(session, account))
        remote = drive.walk_folder(folder.folder_id)
        local = {df.file_id: df for df in session.scalars(select(DriveFile).where(DriveFile.watched_folder_id == folder.id))}
        d = diff(remote, local)
        for f in d["new"]:
            _apply(session, folder, f, None)
        for f in d["changed"]:
            _apply(session, folder, f, local[f["id"]])
        for df in d["unchanged"]:
            local[df["id"]].last_synced_at = utcnow()
        for df in d["removed"]:
            df.status = "removed"
            for doc in session.scalars(select(Document).where(Document.drive_file_id == df.id, Document.is_current.is_(True))):
                doc.is_current = False
        # a crash mid-extraction leaves rows in `extracting`; reset the stale ones
        cutoff = utcnow() - STALE_EXTRACTING
        for df in local.values():
            if df.status == "extracting" and (df.extracting_since or df.created_at) < cutoff:
                df.status = "pending"
        session.flush()
        pending_ids = [df.id for df in session.scalars(select(DriveFile).where(DriveFile.watched_folder_id == folder.id, DriveFile.status == "pending"))]
        summary = {"listed": len(remote), "new": len(d["new"]), "changed": len(d["changed"]), "unchanged": len(d["unchanged"]),
                   "removed": len(d["removed"]), "pending": len(pending_ids), "at": utcnow().isoformat(timespec="seconds")}
        folder.last_tick_at = utcnow()
        folder.last_tick_summary = summary
        session.commit()
    if extract:
        for fid in pending_ids:
            submit(fid, drive)
    return summary


def submit(drive_file_id: int, drive: DriveClient) -> None:
    with _inflight_lock:
        if drive_file_id in _inflight:
            return
        _inflight.add(drive_file_id)
    _pool.submit(_run, drive_file_id, drive)


def _run(drive_file_id: int, drive: DriveClient) -> None:
    try:
        process_drive_file(drive_file_id, drive)
    except Exception:  # noqa: BLE001
        log.exception("drive file %s crashed", drive_file_id)
    finally:
        with _inflight_lock:
            _inflight.discard(drive_file_id)


def process_drive_file(drive_file_id: int, drive: DriveClient, *, force: bool = False) -> None:
    with SessionLocal() as session:
        df = session.get(DriveFile, drive_file_id)
        if df is None or df.status not in ("pending",):
            return
        df.status = "extracting"
        df.extracting_since = utcnow()
        df.attempts += 1
        session.commit()
        try:
            name, mime = df.name, df.mime
            if mime in EXPORTS:
                mime, ext = EXPORTS[mime]
                data = drive.export(df.file_id, mime)
                name = name if name.lower().endswith(ext) else name + ext
            else:
                data = drive.download(df.file_id)
            process_bytes(session, name=name, mime=mime, data=data, source="drive", drive_file=df, force=force)
        except Unsupported as exc:
            df.status = "skipped"
            df.error = str(exc)
            df.extracting_since = None
            session.commit()
        except Exception as exc:  # noqa: BLE001  the row must say why
            df.status = "failed"
            df.error = f"{type(exc).__name__}: {exc}"[:2000]
            df.extracting_since = None
            session.commit()
            log.warning("drive file %s failed: %s", df.name, df.error)


# ---------- scheduler ----------
_stop = threading.Event()
_thread: threading.Thread | None = None


def run_all_folders() -> list[dict[str, Any]]:
    if not _tick_lock.acquire(blocking=False):
        return [{"busy": True}]
    _state["running"] = True
    out: list[dict[str, Any]] = []
    try:
        with SessionLocal() as session:
            ids = [f.id for f in session.scalars(select(WatchedFolder).where(WatchedFolder.active.is_(True)))]
        if settings.watch_dir:
            from . import localfolder
            try:
                out.append(localfolder.tick())
            except Exception as exc:  # noqa: BLE001
                log.exception("local folder tick failed")
                out.append({"folder": "local", "error": f"{type(exc).__name__}: {exc}"[:300]})
        for fid in ids:
            try:
                out.append(tick(fid))
            except auth.ReauthRequired as exc:
                out.append({"folder": fid, "error": f"reauth required: {exc}"})
            except Exception as exc:  # noqa: BLE001
                log.exception("tick failed for folder %s", fid)
                out.append({"folder": fid, "error": f"{type(exc).__name__}: {exc}"[:300]})
        _state["last_tick_at"] = utcnow().isoformat(timespec="seconds")
        _state["last_error"] = "; ".join(str(o.get("error")) for o in out if o.get("error"))
    finally:
        _state["running"] = False
        _tick_lock.release()
    return out


def _loop(interval: int) -> None:
    while not _stop.is_set():
        _state["next_tick_at"] = (utcnow() + timedelta(seconds=interval)).isoformat(timespec="seconds")
        if _stop.wait(interval):
            break
        try:
            run_all_folders()
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick crashed")


def start_scheduler(interval: int | None = None) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval or settings.sync_interval_seconds,), name="sync-loop", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()


def status() -> dict[str, Any]:
    return {**_state, "interval_seconds": settings.sync_interval_seconds, "thread_alive": bool(_thread and _thread.is_alive()),
            "inflight": len(_inflight)}
