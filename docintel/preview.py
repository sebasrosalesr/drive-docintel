"""The original document in a shape the browser can show natively: PDF/HTML by URL, CSV/XLSX as
a grid, DOCX as paragraph/table blocks, .eml as an email."""
from __future__ import annotations

import csv
import email
import io
from email import policy

from .models import Document
from .render import docx_blocks, kind_for, xlsx_sheets

FILE_KINDS = {"pdf": ("PDF", "pdf"), "csv": ("CSV", "csv"), "xlsx": ("Excel", "xlsx"), "docx": ("Word", "docx"),
              "html": ("Web page", "html"), "eml": ("Email", "eml"), "text": ("Text", "txt")}


def file_kind(name: str, mime: str) -> dict:
    kind = kind_for(name, mime)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    label, default_ext = FILE_KINDS.get(kind, ("File", ext))
    if mime == "application/vnd.google-apps.document":
        label = "Google Doc"
    elif mime == "application/vnd.google-apps.spreadsheet":
        label = "Google Sheet"
    return {"kind": kind, "label": label, "ext": ext or default_ext}


def preview(doc: Document, data: bytes) -> dict:
    kind = kind_for(doc.name, doc.mime)
    url = f"/api/documents/{doc.id}/original"
    if kind == "pdf":
        return {"kind": "pdf", "url": url}
    if kind == "html":
        return {"kind": "html", "url": url}
    if kind == "csv":
        s = data.decode("utf-8-sig", "replace")
        try:
            dialect = csv.Sniffer().sniff(s[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(s), dialect))[:500]
        width = max((len(r) for r in rows), default=0)
        return {"kind": "grid", "sheets": [{"name": doc.name, "rows": [r + [""] * (width - len(r)) for r in rows]}]}
    if kind == "xlsx":
        return {"kind": "grid", "sheets": [{"name": n, "rows": r[:500]} for n, r in xlsx_sheets(data)]}
    if kind == "docx":
        return {"kind": "docx", "blocks": docx_blocks(data)}
    if kind == "eml":
        msg = email.message_from_bytes(data, policy=policy.default)
        html_part = msg.get_body(preferencelist=("html",))
        text_part = msg.get_body(preferencelist=("plain",))
        return {"kind": "email", "headers": {k: str(msg.get(k, "")) for k in ("From", "To", "Date", "Subject")},
                "html": html_part.get_content() if html_part is not None else None,
                "text": text_part.get_content() if text_part is not None else "",
                "attachments": [p.get_filename() or "attachment" for p in msg.iter_attachments()]}
    return {"kind": "text", "text": data.decode("utf-8", "replace")[:200_000]}
