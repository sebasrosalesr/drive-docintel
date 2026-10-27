"""Watch a folder on this machine (WATCH_DIR) the same way the Drive folder is watched.

Files are keyed by relative path; change detection uses size + mtime. New or changed files go
through pipeline.process_bytes; files that disappear are marked removed and their figures hidden.
"""
from __future__ import annotations

import logging
import mimetypes
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Document, LocalFile, utcnow
from .pipeline import Unsupported, process_bytes
from .render import kind_for

log = logging.getLogger("docintel.localfolder")
mimetypes.add_type("message/rfc822", ".eml")
STALE = timedelta(minutes=15)
_state: dict[str, Any] = {"last_scan_at": None, "last_summary": None, "error": ""}


def root() -> Path | None:
    return settings.watch_dir


def scan(folder: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or any(part.startswith(".") for part in p.relative_to(folder).parts) or p.name.startswith("~$"):
            continue
        st = p.stat()
        out.append({"id": str(p.relative_to(folder)), "name": p.name, "mimeType": mimetypes.guess_type(p.name)[0] or "",
                    "md5Checksum": "", "version": str(st.st_size), "modifiedTime": str(st.st_mtime_ns), "size": st.st_size})
    return out


def tick(*, extract: bool = True, transport=None) -> dict[str, Any]:
    from .sync import diff, _pool  # late import: sync imports nothing from here

    folder = root()
    if folder is None:
        return {"error": "WATCH_DIR not set"}
    if not folder.is_dir():
        _state["error"] = f"{folder} is not a folder"
        return {"error": _state["error"]}
    remote = scan(folder)
    with SessionLocal() as s:
        local = {lf.rel_path: lf for lf in s.scalars(select(LocalFile))}
        d = diff(remote, local)
        for f in d["new"] + d["changed"]:
            lf = local.get(f["id"]) or LocalFile(rel_path=f["id"])
            if lf.id is None:
                s.add(lf)
            lf.name, lf.mime, lf.version, lf.modified_time, lf.size = f["name"], f["mimeType"], f["version"], f["modifiedTime"], f["size"]
            lf.error, lf.attempts, lf.last_synced_at = "", 0, utcnow()
            supported = kind_for(lf.name, lf.mime) != "unsupported"
            lf.status = "pending" if supported else "skipped"
            if not supported:
                lf.error = f"unsupported type: {lf.mime or lf.name.rsplit('.', 1)[-1]}"
        for f in d["unchanged"]:
            local[f["id"]].last_synced_at = utcnow()
        for lf in d["removed"]:
            lf.status = "removed"
            if lf.current_document_id:
                doc = s.get(Document, lf.current_document_id)
                if doc:
                    doc.is_current = False
        cutoff = utcnow() - STALE
        for lf in local.values():
            if lf.status == "extracting" and (lf.extracting_since or lf.created_at) < cutoff:
                lf.status = "pending"
        s.flush()
        pending = [lf.id for lf in s.scalars(select(LocalFile).where(LocalFile.status == "pending"))]
        summary = {"folder": str(folder), "listed": len(remote), "new": len(d["new"]), "changed": len(d["changed"]), "unchanged": len(d["unchanged"]),
                   "removed": len(d["removed"]), "pending": len(pending), "at": utcnow().isoformat(timespec="seconds")}
        s.commit()
    _state.update({"last_scan_at": summary["at"], "last_summary": summary, "error": ""})
    if extract:
        for lid in pending:
            _pool.submit(process_local_file, lid, transport)
    return summary


def process_local_file(local_file_id: int, transport=None) -> None:
    folder = root()
    with SessionLocal() as s:
        lf = s.get(LocalFile, local_file_id)
        if lf is None or lf.status != "pending" or folder is None:
            return
        lf.status, lf.extracting_since, lf.attempts = "extracting", utcnow(), lf.attempts + 1
        s.commit()
        try:
            data = (folder / lf.rel_path).read_bytes()
            doc = process_bytes(s, name=lf.name, mime=lf.mime, data=data, source="folder", transport=transport)
            lf.status, lf.error, lf.current_document_id = doc.status, doc.error, doc.id
        except Unsupported as exc:
            lf.status, lf.error = "skipped", str(exc)
        except Exception as exc:  # noqa: BLE001
            lf.status, lf.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            log.warning("local file %s failed: %s", lf.name, lf.error)
        lf.extracting_since = None
        s.commit()


def status() -> dict[str, Any]:
    folder = root()
    return {"watch_dir": str(folder) if folder else None, "exists": bool(folder and folder.is_dir()), **_state}
