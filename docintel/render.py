"""Bytes → text (and a few facts) for every supported format.

PDF text here is for the raw-text tab, evidence verification and the scanned check; the
model reads the PDF itself. HTML, .eml and CSV are rendered to text the model reads.
"""
from __future__ import annotations

import csv
import email
import io
import re
from dataclasses import dataclass, field
from email import policy
from html.parser import HTMLParser

PDF_MIMES = {"application/pdf"}
CSV_MIMES = {"text/csv", "application/csv", "text/comma-separated-values"}
HTML_MIMES = {"text/html", "application/xhtml+xml"}
EML_MIMES = {"message/rfc822"}
TEXT_MIMES = {"text/plain", "text/markdown"}
XLSX_MIMES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel.sheet.macroenabled.12"}
DOCX_MIMES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
GOOGLE_FOLDER = "application/vnd.google-apps.folder"
GOOGLE_SHORTCUT = "application/vnd.google-apps.shortcut"
MAX_TEXT_CHARS = 2_000_000
LOW_TEXT_CHARS = 200          # a page with fewer characters gets the next tier
MAX_OCR_PAGES = 40


@dataclass
class Rendered:
    kind: str                      # pdf | csv | html | eml | text | xlsx | docx | pptx | image | unsupported
    text: str = ""
    pages: int = 0
    is_scanned: bool = False
    note: str = ""
    attachments: list[str] = field(default_factory=list)
    ocr_pages: int = 0
    image_mime: str = ""
    table: list[list[str]] | None = None     # csv / first sheet of xlsx, every row


IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".tif": "image/tiff", ".tiff": "image/tiff"}
PPTX_MIMES = {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}


def kind_for(name: str, mime: str) -> str:
    n = name.lower()
    if mime in PDF_MIMES or n.endswith(".pdf"):
        return "pdf"
    if mime in CSV_MIMES or n.endswith((".csv", ".tsv")):
        return "csv"
    if mime in EML_MIMES or n.endswith(".eml"):
        return "eml"
    if mime in HTML_MIMES or n.endswith((".html", ".htm")):
        return "html"
    if mime in TEXT_MIMES or n.endswith((".txt", ".md")):
        return "text"
    if mime in XLSX_MIMES or n.endswith((".xlsx", ".xlsm")):
        return "xlsx"
    if mime in DOCX_MIMES or n.endswith(".docx"):
        return "docx"
    if mime in PPTX_MIMES or n.endswith(".pptx"):
        return "pptx"
    if (mime or "").startswith("image/") or any(n.endswith(e) for e in IMAGE_EXT):
        return "image"
    return "unsupported"


def image_mime(name: str, mime: str) -> str:
    if (mime or "").startswith("image/"):
        return mime
    for e, m in IMAGE_EXT.items():
        if name.lower().endswith(e):
            return m
    return "image/png"


# ---------- XLSX ----------
def _cell_str(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def xlsx_sheets(data: bytes, max_rows: int = 400) -> list[tuple[str, list[list[str]]]]:
    """[(sheet name, rows)] with trailing empty rows/columns trimmed."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows: list[list[str]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            rows.append([_cell_str(v) for v in row])
        while rows and not any(rows[-1]):
            rows.pop()
        width = max((len(r) for r in rows), default=0)
        while width and not any(r[width - 1] if len(r) >= width else "" for r in rows):
            width -= 1
        rows = [(r + [""] * width)[:width] for r in rows]
        out.append((ws.title, rows))
    return out


def _md(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    lines = ["| " + " | ".join(c.strip() for c in rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(c.strip() for c in r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def xlsx_text(data: bytes) -> str:
    parts = [f"## Sheet: {name}\n{_md(rows)}" for name, rows in xlsx_sheets(data)]
    return "\n\n".join(parts)[:MAX_TEXT_CHARS]


# ---------- DOCX ----------
def docx_blocks(data: bytes) -> list[dict]:
    """Paragraphs and tables in document order: {type: p, text, style} | {type: table, rows}."""
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = DocxDocument(io.BytesIO(data))
    blocks: list[dict] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            if para.text.strip():
                blocks.append({"type": "p", "text": para.text, "style": (para.style.name if para.style is not None else "")})
        elif tag == "tbl":
            table = Table(child, doc)
            blocks.append({"type": "table", "rows": [[c.text for c in row.cells] for row in table.rows]})
    return blocks


def docx_text(data: bytes) -> str:
    parts = []
    for b in docx_blocks(data):
        parts.append(_md(b["rows"]) if b["type"] == "table" else b["text"])
    return "\n\n".join(parts)[:MAX_TEXT_CHARS]


# ---------- PDF: tiered per page ----------
def _pdftotext_layout(data: bytes) -> list[str] | None:
    """poppler's pdftotext -layout keeps table rows on one line; pages are separated by form feeds."""
    import shutil
    import subprocess

    if not shutil.which("pdftotext"):
        return None
    try:
        out = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, timeout=90, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    pages = out.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _pypdf_pages(data: bytes) -> list[str]:
    import logging as _logging

    from pypdf import PdfReader

    _logging.getLogger("pypdf").setLevel(_logging.ERROR)
    reader = PdfReader(io.BytesIO(data))
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001  odd fonts
            out.append("")
    return out


def _plumber_page(data: bytes, index: int) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return pdf.pages[index].extract_text() or ""
    except Exception:  # noqa: BLE001
        return ""


def _ocr_page(data: bytes, index: int) -> str:
    """Tesseract on one rasterised page (poppler + pytesseract). '' when the tools are missing."""
    try:
        import pytesseract
        from pdf2image import convert_from_bytes

        imgs = convert_from_bytes(data, dpi=200, first_page=index + 1, last_page=index + 1)
        return pytesseract.image_to_string(imgs[0]) if imgs else ""
    except Exception:  # noqa: BLE001
        return ""


def pdf_text(data: bytes) -> tuple[str, int, bool, int]:
    """(text with page markers, pages, is_scanned, ocr_pages).
    Tier 1 pdftotext -layout (or pypdf), tier 2 pdfplumber for thin pages, tier 3 Tesseract for pages with no text."""
    layout = _pdftotext_layout(data)
    base = layout if layout else _pypdf_pages(data)
    if layout:
        pyp = None
    pages = len(base)
    out = []
    ocr = 0
    for i, t in enumerate(base):
        if len(t.strip()) < LOW_TEXT_CHARS:
            alt = _plumber_page(data, i)
            if len(alt.strip()) > len(t.strip()):
                t = alt
        if len(t.strip()) < LOW_TEXT_CHARS and ocr < MAX_OCR_PAGES:
            o = _ocr_page(data, i)
            if len(o.strip()) > len(t.strip()):
                t = o
                ocr += 1
        out.append(f"--- page {i + 1} ---\n{t}")
    text = "\n".join(out)
    chars = sum(len(t) for t in base)
    return text[:MAX_TEXT_CHARS], pages, pages > 0 and chars / pages < 50, ocr


def image_text(data: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception:  # noqa: BLE001
        return ""


# ---------- PPTX ----------
def pptx_text(data: bytes) -> tuple[str, int]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        lines = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                lines.append(_md([[c.text for c in row.cells] for row in shape.table.rows]))
        parts.append(f"--- slide {i} ---\n" + "\n".join(lines))
    return "\n".join(parts)[:MAX_TEXT_CHARS], len(prs.slides)


# ---------- HTML ----------
class _Html2Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "header", "footer"}
    SKIP = {"script", "style", "head", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)

    def text(self) -> str:
        raw = "".join(self.out)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n", raw)
        return raw.strip()


def html_text(data: bytes | str) -> str:
    s = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    p = _Html2Text()
    p.feed(s)
    return p.text()[:MAX_TEXT_CHARS]


# ---------- EML ----------
def eml_text(data: bytes) -> tuple[str, list[str]]:
    msg = email.message_from_bytes(data, policy=policy.default)
    header = "\n".join(f"{k}: {msg.get(k, '')}" for k in ("From", "To", "Date", "Subject"))
    body = ""
    attachments: list[str] = []
    html_part = msg.get_body(preferencelist=("html",))
    text_part = msg.get_body(preferencelist=("plain",))
    if html_part is not None:
        body = html_text(html_part.get_content())
    elif text_part is not None:
        body = text_part.get_content()
    for part in msg.iter_attachments():
        attachments.append(part.get_filename() or "attachment")
    note = f"\n\n[attachments not processed: {', '.join(attachments)}]" if attachments else ""
    return (header + "\n\n" + body + note)[:MAX_TEXT_CHARS], attachments


# ---------- CSV ----------
def csv_rows(data: bytes) -> list[list[str]]:
    s = data.decode("utf-8-sig", "replace")
    try:
        dialect = csv.Sniffer().sniff(s[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(s), dialect)]
    rows = [r for r in rows if not (len(r) == 1 and r[0].startswith("#"))]   # comment lines
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def csv_table(data: bytes, max_rows: int = 400) -> str:
    rows = csv_rows(data)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, body = rows[0], rows[1:max_rows + 1]
    lines = ["| " + " | ".join(c.strip() for c in head) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(c.strip() for c in r) + " |" for r in body]
    if len(rows) - 1 > max_rows:
        lines.append(f"... {len(rows) - 1 - max_rows} more rows not shown ...")
    return "\n".join(lines)[:MAX_TEXT_CHARS]


def render(name: str, mime: str, data: bytes) -> Rendered:
    kind = kind_for(name, mime)
    if kind == "pdf":
        text, pages, scanned, ocr = pdf_text(data)
        return Rendered(kind, text, pages, scanned, ocr_pages=ocr)
    if kind == "pptx":
        text, n = pptx_text(data)
        return Rendered(kind, text, n)
    if kind == "image":
        t = image_text(data)
        return Rendered(kind, t, 1, is_scanned=len(t.strip()) < 50, ocr_pages=1 if t.strip() else 0, image_mime=image_mime(name, mime))
    if kind == "csv":
        return Rendered(kind, csv_table(data), 1, table=csv_rows(data))
    if kind == "html":
        return Rendered(kind, html_text(data), 1)
    if kind == "eml":
        text, atts = eml_text(data)
        return Rendered(kind, text, 1, attachments=atts)
    if kind == "text":
        return Rendered(kind, data.decode("utf-8", "replace")[:MAX_TEXT_CHARS], 1)
    if kind == "xlsx":
        sheets = xlsx_sheets(data)
        return Rendered(kind, xlsx_text(data), 1, table=sheets[0][1] if sheets else None)
    if kind == "docx":
        return Rendered(kind, docx_text(data), 1)
    return Rendered("unsupported", note=f"unsupported type: {mime or name.rsplit('.', 1)[-1]}")
