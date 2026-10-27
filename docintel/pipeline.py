"""Process one file: bytes → render → extract → normalize → validate → persist.

Used by the Drive sync and by scripts/run_local.py alike, so the same code path is
exercised with or without Google.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import llm
from . import pii
from . import render as rend
from .config import settings
from .models import Document, DriveFile, Fact, LLMCall, Observation, utcnow
from .normalize import page_texts, parse_date, period_fields, resolve_fund, verify_evidence
from .tabular import LARGE_TABLE_ROWS
from .validate import validate

log = logging.getLogger("docintel.pipeline")


class Unsupported(Exception):
    pass


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def blob_path(sha: str):
    d = settings.data_dir / "blobs"
    d.mkdir(parents=True, exist_ok=True)
    return d / sha


def store_blob(sha: str, data: bytes) -> None:
    p = blob_path(sha)
    if not p.exists():
        p.write_bytes(data)


def load_blob(sha: str) -> bytes | None:
    p = blob_path(sha)
    return p.read_bytes() if p.exists() else None


def _supersede(session: Session, doc: Document, drive_file: DriveFile | None) -> None:
    q = select(Document).where(Document.is_current.is_(True), Document.id != doc.id)
    q = q.where(Document.drive_file_id == drive_file.id) if drive_file else q.where(Document.source == doc.source, Document.name == doc.name)
    for old in session.scalars(q):
        old.is_current = False
    if drive_file:
        drive_file.current_document_id = doc.id
        drive_file.status = doc.status
        drive_file.error = doc.error
        drive_file.extracting_since = None


def _record_call(session: Session, doc_id: int | None, meta: dict[str, Any], *, ok: bool, error: str = "") -> None:
    session.add(LLMCall(
        document_id=doc_id, purpose="extract", model=meta.get("model", ""),
        input_tokens=meta.get("input_tokens", 0), output_tokens=meta.get("output_tokens", 0),
        cost_usd=meta.get("cost_usd", 0.0), duration_ms=meta.get("duration_ms", 0),
        finish_reason=meta.get("finish_reason", ""), ok=ok, error=error[:2000],
    ))


def process_bytes(
    session: Session,
    *,
    name: str,
    mime: str,
    data: bytes,
    source: str = "local",
    drive_file: DriveFile | None = None,
    force: bool = False,
    transport: llm.Transport | None = None,
    engine: str | None = None,
    effort: str | None = None,
    model: str | None = None,
    parent_document_id: int | None = None,
    _depth: int = 0,
) -> Document:
    sha = sha256(data)
    store_blob(sha, data)
    if not force:
        q = select(Document).where(Document.sha256 == sha, Document.is_current.is_(True), Document.status != "failed")
        q = q.where(Document.drive_file_id == drive_file.id) if drive_file else q.where(Document.source == source, Document.name == name)
        existing = session.scalar(q)
        if existing is not None:
            if drive_file:
                drive_file.status = existing.status
                drive_file.current_document_id = existing.id
                drive_file.extracting_since = None
                session.commit()
            return existing

    r = rend.render(name, mime, data)
    if r.kind == "unsupported":
        raise Unsupported(r.note)

    # ---- PII gate: runs on the local text/OCR layer before any model call ----
    scr = pii.screen(r.text, name)
    if scr.identity and settings.pii_identity_policy != "allow":
        doc = Document(
            drive_file_id=drive_file.id if drive_file else None, parent_document_id=parent_document_id, source=source, name=name, mime=mime, sha256=sha, text_sha256="",
            page_count=r.pages, is_scanned=r.is_scanned, raw_text="", ocr_pages=r.ocr_pages, doc_type="identity_document",
            title=f"Personal ID document ({scr.identity_label})", status="rejected",
            error=f"Rejected before any model call: this looks like a {scr.identity_label} (matched: {', '.join(scr.reasons[:4])}). Nothing was sent or stored.",
            validation_json={"status": "rejected", "flags": [{"code": "identity_document", "msg": f"Looks like a {scr.identity_label}"}], "n_metrics": 0, "n_rows": 0, "n_facts": 0, "pii": {"identity": scr.identity, "scores": scr.scores}},
        )
        session.add(doc)
        session.flush()
        _supersede(session, doc, drive_file)
        session.commit()
        try:
            blob_path(sha).unlink(missing_ok=True)   # keep nothing
        except OSError:
            pass
        log.warning("%s rejected as %s", name, scr.identity_label)
        return doc
    redacted = bool(scr.redactions) and settings.pii_redact
    stored_text = scr.redacted_text if redacted else r.text

    doc = Document(
        drive_file_id=drive_file.id if drive_file else None, parent_document_id=parent_document_id, source=source, name=name, mime=mime,
        sha256=sha, text_sha256=sha256(stored_text), page_count=r.pages, is_scanned=r.is_scanned, raw_text=stored_text, ocr_pages=r.ocr_pages,
    )
    started = time.perf_counter()
    meta: dict[str, Any] = {}
    mapped = False
    try:
        if redacted:
            # sensitive identifiers inside: the model gets the masked text, never the original bytes
            ex, meta = llm.extract(name, text=stored_text, kind=r.kind, effort=effort, model=model, transport=transport)
            meta["engine"] = "text-redacted"
        elif r.kind == "pdf":
            ex, meta = llm.extract(name, pdf_bytes=data, engine=engine, effort=effort, model=model, transport=transport)
            used_engine = engine or settings.pdf_engine
            if not ex.metrics and r.is_scanned and used_engine == "native":
                log.info("%s: scanned PDF returned no metrics natively; retrying with mistral-ocr", name)
                ex2, meta2 = llm.extract(name, pdf_bytes=data, engine="mistral-ocr", effort=effort, model=model, transport=transport)
                for k in ("input_tokens", "output_tokens", "cost_usd", "duration_ms"):
                    meta2[k] = meta2.get(k, 0) + meta.get(k, 0)
                if ex2.metrics:
                    ex, meta = ex2, meta2
        elif r.kind == "image":
            ex, meta = llm.extract(name, image=(data, r.image_mime), effort=effort, model=model, transport=transport)
        elif r.kind in ("csv", "xlsx") and r.table and len(r.table) > LARGE_TABLE_ROWS:
            from .tabular import apply_mapping
            mp, meta = llm.map_table(name, r.table, effort=effort, model=model, transport=transport)
            ex, skipped = apply_mapping(r.table, mp)
            mapped = True
            log.info("%s: %d rows mapped (%s layout), %d skipped", name, len(ex.metrics), mp.layout, len(skipped))
        else:
            ex, meta = llm.extract(name, text=r.text, kind=r.kind, effort=effort, model=model, transport=transport)
    except Exception as exc:  # noqa: BLE001  the row must record why
        doc.status = "failed"
        doc.error = f"{type(exc).__name__}: {exc}"[:2000]
        doc.duration_ms = int((time.perf_counter() - started) * 1000)
        session.add(doc)
        session.flush()
        _record_call(session, doc.id, meta, ok=False, error=doc.error)
        _supersede(session, doc, drive_file)
        session.commit()
        log.warning("%s failed: %s", name, doc.error)
        return doc

    as_of = parse_date(ex.as_of_date)
    doc.doc_type = ex.doc_type
    manager = ex.manager.strip()[:300]
    doc.manager = manager.title() if manager.isupper() else manager   # "NORTHWIND CAPITAL MANAGEMENT" as printed → readable
    doc.as_of_date = as_of
    doc.currency = ex.currency.strip()[:10]
    doc.title = ex.title.strip()[:300]
    doc.summary = ex.summary.strip()
    doc.key_points = [k.strip() for k in ex.key_points if k.strip()][:8]
    doc.extraction_json = ex.model_dump()
    doc.model = meta.get("model", "")
    doc.engine = meta.get("engine", "")
    doc.cost_usd = meta.get("cost_usd", 0.0)
    doc.usage_json = {k: meta.get(k) for k in ("input_tokens", "output_tokens", "finish_reason", "prompt_version")}
    doc.duration_ms = int((time.perf_counter() - started) * 1000)
    session.add(doc)
    session.flush()

    rows: list[dict[str, Any]] = []
    default_fund = ex.funds[0].name if ex.funds else name
    pages = page_texts(r.text)
    scanned = r.kind in ("pdf", "image") and r.is_scanned
    for m in ex.metrics:
        fund = resolve_fund(session, (m.fund_name or default_fund).strip()[:300], doc.manager)
        pf = period_fields(m.period, as_of)
        ok, note = (True, "table-row") if mapped else verify_evidence(m.evidence_text, r.text, scanned=scanned, page=m.page, pages=pages)
        obs = Observation(
            fund_id=fund.id, document_id=doc.id, metric=m.metric, metric_label=m.metric_label[:200],
            share_class=m.share_class[:100], period_label=m.period.label[:100], **pf,
            value=m.value, unit=m.unit, annualized=m.annualized, basis=m.basis,
            currency=(m.currency or ex.currency).strip()[:10], evidence_text=m.evidence_text[:1000],
            evidence_verified=ok, evidence_note=note, page=m.page, confidence=m.confidence,
        )
        session.add(obs)
        rows.append({"fund_id": fund.id, "share_class": obs.share_class, "basis": obs.basis, "metric": obs.metric,
                     "unit": obs.unit, "value": obs.value, "period_type": obs.period_type,
                     "period_year": obs.period_year, "period_month": obs.period_month,
                     "evidence_verified": ok, "evidence_note": note})

    for f in ex.facts:
        ok, note = verify_evidence(f.evidence_text, r.text, scanned=scanned, page=f.page, pages=pages)
        session.add(Fact(
            document_id=doc.id, subject=f.subject.strip()[:300], attribute=f.attribute.strip()[:200], value_text=f.value_text.strip()[:500],
            value_number=f.value_number, unit=f.unit, currency=(f.currency or ex.currency).strip()[:10], as_of=parse_date(f.as_of),
            evidence_text=f.evidence_text[:1000], evidence_verified=ok, evidence_note=note, page=f.page, confidence=f.confidence,
        ))

    v = validate(ex, rows)
    if redacted:
        v["pii"] = {"redactions": scr.redactions, "n": scr.n_redactions}
        v["flags"].append({"code": "pii_redacted", "msg": f"{scr.n_redactions} sensitive identifier(s) masked before the model saw the text: " + ", ".join(f"{k} ×{n}" for k, n in scr.redactions.items())})
    doc.validation_json = v
    doc.status = v["status"]
    _record_call(session, doc.id, meta, ok=True)
    _supersede(session, doc, drive_file)
    session.commit()
    log.info("%s: %s, %d rows, $%.4f, %d ms", name, doc.status, len(rows), doc.cost_usd, doc.duration_ms)
    if r.kind == "eml" and r.attachments and _depth == 0:
        _process_email_attachments(session, doc, data, source=source, force=force, transport=transport, model=model, effort=effort)
    return doc


def _process_email_attachments(session: Session, parent: Document, data: bytes, **kw: Any) -> None:
    """Each supported attachment becomes its own document, linked to the email."""
    import email
    from email import policy

    from .render import kind_for

    msg = email.message_from_bytes(data, policy=policy.default)
    for part in msg.iter_attachments():
        fname = part.get_filename() or "attachment"
        mime = part.get_content_type() or ""
        if kind_for(fname, mime) == "unsupported":
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload or len(payload) > 25 * 1024 * 1024:
            continue
        try:
            process_bytes(session, name=f"{parent.name} » {fname}", mime=mime, data=payload, parent_document_id=parent.id, _depth=1, **kw)
        except Unsupported:
            continue
        except Exception:  # noqa: BLE001  one bad attachment must not sink the email
            log.exception("attachment %s of %s failed", fname, parent.name)
