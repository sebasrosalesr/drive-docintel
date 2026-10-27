"""Google Drive v3: list folders, walk one folder recursively, download or export files."""
from __future__ import annotations

import io
import re
from typing import Any, Protocol

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .render import GOOGLE_FOLDER, GOOGLE_SHORTCUT

FILE_FIELDS = "id,name,mimeType,md5Checksum,modifiedTime,size,version,parents,shortcutDetails,trashed"
LIST_FIELDS = f"nextPageToken, files({FILE_FIELDS})"


class DriveClient(Protocol):
    def list_folders(self, q: str = "") -> list[dict[str, Any]]: ...
    def folder_meta(self, folder_id: str) -> dict[str, Any]: ...
    def walk_folder(self, folder_id: str) -> list[dict[str, Any]]: ...
    def download(self, file_id: str) -> bytes: ...
    def export(self, file_id: str, mime: str) -> bytes: ...


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def parse_folder_ref(ref: str) -> str:
    """Folder URL or bare id → id."""
    ref = ref.strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", ref) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", ref)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", ref):
        return ref
    raise ValueError("not a Drive folder URL or id")


class GoogleDrive:
    def __init__(self, creds) -> None:
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_folders(self, q: str = "") -> list[dict[str, Any]]:
        query = f"mimeType='{GOOGLE_FOLDER}' and trashed=false"
        if q.strip():
            query += f" and name contains '{_esc(q.strip())}'"
        res = self.svc.files().list(q=query, fields="files(id,name,modifiedTime,parents)", pageSize=100, orderBy="modifiedTime desc",
                                    supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        return res.get("files", [])

    def folder_meta(self, folder_id: str) -> dict[str, Any]:
        return self.svc.files().get(fileId=folder_id, fields="id,name,mimeType", supportsAllDrives=True).execute()

    def walk_folder(self, folder_id: str, max_depth: int = 6) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        queue: list[tuple[str, str, int]] = [(folder_id, "", 0)]
        seen: set[str] = set()
        while queue:
            fid, path, depth = queue.pop(0)
            if fid in seen or depth > max_depth:
                continue
            seen.add(fid)
            token = None
            while True:
                res = self.svc.files().list(q=f"'{fid}' in parents and trashed=false", fields=LIST_FIELDS, pageSize=200,
                                            pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
                for f in res.get("files", []):
                    mt = f.get("mimeType", "")
                    if mt == GOOGLE_FOLDER:
                        queue.append((f["id"], f"{path}/{f['name']}", depth + 1))
                    elif mt == GOOGLE_SHORTCUT:
                        tgt = (f.get("shortcutDetails") or {})
                        if tgt.get("targetMimeType") and tgt.get("targetMimeType") != GOOGLE_FOLDER and tgt.get("targetId"):
                            try:
                                meta = self.svc.files().get(fileId=tgt["targetId"], fields=FILE_FIELDS, supportsAllDrives=True).execute()
                                meta["path"] = path
                                out.append(meta)
                            except Exception:  # noqa: BLE001  dangling shortcut
                                pass
                    else:
                        f["path"] = path
                        out.append(f)
                token = res.get("nextPageToken")
                if not token:
                    break
        return out

    def _drain(self, request) -> bytes:
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue()

    def download(self, file_id: str) -> bytes:
        return self._drain(self.svc.files().get_media(fileId=file_id, supportsAllDrives=True))

    def export(self, file_id: str, mime: str) -> bytes:
        return self._drain(self.svc.files().export_media(fileId=file_id, mimeType=mime))
