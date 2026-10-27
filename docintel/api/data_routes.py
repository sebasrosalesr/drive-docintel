from __future__ import annotations

import io
import mimetypes
import threading
import time
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from .. import sync
from ..models import Document, DriveFile, Fact, Fund, LLMCall, LocalFile, Observation
from ..pipeline import load_blob, process_bytes
from ..prompts import PROMPT_VERSION
from ..normalize import norm_fund_name
import difflib
from ..preview import file_kind, preview
from ..render import kind_for

mimetypes.add_type("message/rfc822", ".eml")

# Files uploaded through the UI, until their document row exists: name -> {started, status, error}
_uploads: dict[str, dict] = {}
_uploads_lock = threading.Lock()
from .deps import get_session

router = APIRouter(prefix="/api", tags=["data"])


def _doc_summary(d: Document | None) -> dict | None:
    if d is None:
        return None
    v = d.validation_json or {}
    return {"document_id": d.id, "doc_type": d.doc_type, "manager": d.manager, "as_of_date": d.as_of_date.isoformat() if d.as_of_date else None,
            "currency": d.currency, "status": d.status, "error": d.error, "n_rows": v.get("n_rows", 0),
            "flags": [f for f in v.get("flags", []) if f.get("code") != "model_warning"], "warnings": [f["msg"] for f in v.get("flags", []) if f.get("code") == "model_warning"],
            "cost_usd": d.cost_usd, "duration_ms": d.duration_ms, "is_scanned": d.is_scanned, "page_count": d.page_count, "ocr_pages": d.ocr_pages,
            "title": d.title, "summary": d.summary, "key_points": d.key_points or [], "n_facts": v.get("n_facts", 0),
            "model": d.model, "engine": d.engine, "created_at": d.created_at.isoformat(timespec="seconds")}


@router.get("/documents")
def documents(session: Session = Depends(get_session)):
    items = []
    docs_by_id = {d.id: d for d in session.scalars(select(Document).where(Document.is_current.is_(True)))}
    for df in session.scalars(select(DriveFile).where(DriveFile.status != "removed").order_by(DriveFile.created_at.desc())):
        items.append({"key": f"f{df.id}", "source": "drive", "file_id": df.id, "name": df.name, "mime": df.mime, "file": file_kind(df.name, df.mime), "status": df.status,
                      "error": df.error, "attempts": df.attempts, "modified_time": df.modified_time, "size": df.size,
                      "document": _doc_summary(docs_by_id.get(df.current_document_id or -1))})
    for lf in session.scalars(select(LocalFile).where(LocalFile.status != "removed").order_by(LocalFile.created_at.desc())):
        items.append({"key": f"l{lf.id}", "source": "folder", "file_id": None, "name": lf.name, "mime": lf.mime, "file": file_kind(lf.name, lf.mime), "status": lf.status,
                      "error": lf.error, "attempts": lf.attempts, "modified_time": lf.last_synced_at.isoformat(timespec="seconds") if lf.last_synced_at else "", "size": lf.size,
                      "document": _doc_summary(docs_by_id.get(lf.current_document_id or -1))})
    with _uploads_lock:
        pending = {k: dict(v) for k, v in _uploads.items()}
    for name, u in sorted(pending.items(), key=lambda kv: kv[1]["started"], reverse=True):
        items.append({"key": f"u{name}", "source": "upload", "file_id": None, "name": name, "mime": u.get("mime", ""), "file": file_kind(name, u.get("mime", "")),
                      "status": u["status"], "error": u.get("error", ""), "attempts": 1, "modified_time": "", "size": u.get("size", 0), "document": None})
    for d in sorted((d for d in docs_by_id.values() if d.drive_file_id is None and (d.source != "folder" or d.parent_document_id)), key=lambda d: d.created_at, reverse=True):
        items.append({"key": f"d{d.id}", "source": "attachment" if d.parent_document_id else ("sample" if d.source == "sample" else "local"), "file_id": None, "name": d.name, "mime": d.mime, "file": file_kind(d.name, d.mime), "status": d.status,
                      "error": d.error, "attempts": 1, "modified_time": d.created_at.isoformat(timespec="seconds"), "size": 0,
                      "document": _doc_summary(d), "parent_document_id": d.parent_document_id})
    return {"items": items}


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Drop files in without Drive. Each goes through the same pipeline in the background."""
    accepted, rejected = [], []
    for f in files:
        name = (f.filename or "upload").rsplit("/", 1)[-1]
        data = await f.read()
        mime = f.content_type or mimetypes.guess_type(name)[0] or ""
        if kind_for(name, mime) == "unsupported":
            rejected.append({"name": name, "reason": "unsupported file type"})
            continue
        if not data:
            rejected.append({"name": name, "reason": "empty file"})
            continue
        with _uploads_lock:
            _uploads[name] = {"started": time.time(), "status": "extracting", "mime": mime, "size": len(data)}

        def work(name=name, mime=mime, data=data):
            from ..db import SessionLocal
            try:
                with SessionLocal() as s:
                    process_bytes(s, name=name, mime=mime, data=data, source="local", force=True)
                with _uploads_lock:
                    _uploads.pop(name, None)
            except Exception as exc:  # noqa: BLE001
                with _uploads_lock:
                    _uploads[name] = {**_uploads.get(name, {}), "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}

        sync._pool.submit(work)
        accepted.append(name)
    return {"accepted": accepted, "rejected": rejected}


@router.get("/tutorial/status")
def tutorial_status(session: Session = Depends(get_session)):
    n = session.execute(select(func.count()).select_from(Document).where(Document.is_current.is_(True))).scalar() or 0
    n_sample = session.execute(select(func.count()).select_from(Document).where(Document.is_current.is_(True), Document.source == "sample")).scalar() or 0
    from ..config import settings as cfg
    return {"documents": n, "sample_documents": n_sample, "llm_ready": cfg.llm_ready}


@router.post("/tutorial/sample")
def tutorial_sample():
    """Generate the fictional corpus (13 documents, 5 managers) and read it, so the tour has something to show on a fresh install."""
    import importlib.util
    import sys
    from ..config import ROOT, settings as cfg
    if not cfg.llm_ready:
        raise HTTPException(503, "OPENROUTER_API_KEY is not set")
    out = cfg.data_dir / "sample_corpus"
    spec = importlib.util.spec_from_file_location("make_corpus", ROOT / "scripts" / "make_corpus.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["make_corpus"] = mod
    spec.loader.exec_module(mod)
    sys.argv = ["make_corpus", "--out", str(out)]
    mod.main()
    files = sorted(p for p in out.iterdir() if p.is_file() and p.suffix != ".json" and kind_for(p.name, "") != "unsupported")
    for path in files:
        data = path.read_bytes()
        name = path.name
        mime = mimetypes.guess_type(name)[0] or ""
        with _uploads_lock:
            _uploads[name] = {"started": time.time(), "status": "extracting", "mime": mime, "size": len(data)}

        def work(name=name, mime=mime, data=data):
            from ..db import SessionLocal
            try:
                with SessionLocal() as s:
                    process_bytes(s, name=name, mime=mime, data=data, source="sample", force=True)
                with _uploads_lock:
                    _uploads.pop(name, None)
            except Exception as exc:  # noqa: BLE001
                with _uploads_lock:
                    _uploads[name] = {**_uploads.get(name, {}), "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}

        sync._pool.submit(work)
    return {"queued": len(files), "folder": str(out)}


@router.get("/documents/{doc_id}")
def document(doc_id: int, session: Session = Depends(get_session)):
    d = session.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "no such document")
    obs = session.execute(
        select(Observation, Fund.name).join(Fund, Fund.id == Observation.fund_id).where(Observation.document_id == d.id).order_by(Observation.id)
    ).all()
    calls = session.scalars(select(LLMCall).where(LLMCall.document_id == d.id).order_by(LLMCall.id)).all()
    facts = session.scalars(select(Fact).where(Fact.document_id == d.id).order_by(Fact.id)).all()
    return {
        "facts": [{"id": f.id, "subject": f.subject, "attribute": f.attribute, "value_text": f.value_text, "value_number": f.value_number, "unit": f.unit,
                   "currency": f.currency, "as_of": f.as_of.isoformat() if f.as_of else None, "evidence_text": f.evidence_text, "evidence_verified": f.evidence_verified,
                   "evidence_note": f.evidence_note, "page": f.page, "confidence": f.confidence} for f in facts],
        **(_doc_summary(d) or {}), "name": d.name, "mime": d.mime, "source": d.source, "sha256": d.sha256, "file": file_kind(d.name, d.mime),
        "extraction": d.extraction_json, "validation": d.validation_json, "raw_text": d.raw_text,
        "observations": [{"id": o.id, "fund": fname, "fund_id": o.fund_id, "share_class": o.share_class, "metric": o.metric, "metric_label": o.metric_label,
                          "period_type": o.period_type, "period_label": o.period_label, "period_year": o.period_year, "period_month": o.period_month,
                          "period_start": o.period_start.isoformat() if o.period_start else None, "period_end": o.period_end.isoformat() if o.period_end else None,
                          "value": o.value, "unit": o.unit, "annualized": o.annualized, "basis": o.basis, "currency": o.currency,
                          "evidence_text": o.evidence_text, "evidence_verified": o.evidence_verified, "evidence_note": o.evidence_note,
                          "page": o.page, "confidence": o.confidence} for o, fname in obs],
        "llm_calls": [{"purpose": c.purpose, "model": c.model, "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
                       "cost_usd": c.cost_usd, "duration_ms": c.duration_ms, "ok": c.ok, "error": c.error} for c in calls],
    }


@router.get("/documents/{doc_id}/original")
def original(doc_id: int, session: Session = Depends(get_session)):
    d = session.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "no such document")
    data = load_blob(d.sha256)
    if data is None:
        raise HTTPException(404, "original bytes not kept")
    return StreamingResponse(io.BytesIO(data), media_type=d.mime or "application/octet-stream",
                             headers={"Content-Disposition": f'inline; filename="{d.name}"'})


@router.get("/documents/{doc_id}/preview")
def document_preview(doc_id: int, session: Session = Depends(get_session)):
    d = session.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "no such document")
    if d.status == "rejected":
        return {"kind": "text", "text": "", "note": "This file was rejected by the PII gate. It was not sent to the model and its content was not kept."}
    data = load_blob(d.sha256)
    if data is None:
        return {"kind": "text", "text": d.raw_text, "note": "original bytes not kept; showing extracted text"}
    try:
        return preview(d, data)
    except Exception as exc:  # noqa: BLE001
        return {"kind": "text", "text": d.raw_text, "note": f"preview failed ({type(exc).__name__}); showing extracted text"}


def _queue_rerun(d: Document, effort: str | None = None, engine: str | None = None, model: str | None = None) -> bool:
    data = load_blob(d.sha256)
    if data is None:
        return False
    name, mime, source, dfid = d.name, d.mime, d.source, d.drive_file_id

    def work():
        from ..db import SessionLocal
        with SessionLocal() as s:
            df = s.get(DriveFile, dfid) if dfid else None
            if df:
                df.status = "extracting"
                df.extracting_since = func.now()
                s.commit()
            new = process_bytes(s, name=name, mime=mime, data=data, source=source, drive_file=df, force=True, effort=effort, engine=engine, model=model)
            if source == "folder":
                lf = s.scalar(select(LocalFile).where(LocalFile.name == name))
                if lf:
                    lf.current_document_id, lf.status, lf.error = new.id, new.status, new.error
                    s.commit()

    sync._pool.submit(work)
    return True


@router.post("/documents/rerun-all")
def rerun_all(scope: str = "outdated", session: Session = Depends(get_session)):
    """Queue a re-read of every current document (scope=all) or only those read with an older prompt (scope=outdated)."""
    docs = session.scalars(select(Document).where(Document.is_current.is_(True), Document.status != "rejected")).all()
    queued, skipped = 0, 0
    for d in docs:
        pv = (d.usage_json or {}).get("prompt_version", "")
        if scope == "outdated" and pv == PROMPT_VERSION:
            continue
        if _queue_rerun(d):
            queued += 1
        else:
            skipped += 1
    return {"queued": queued, "skipped_no_original": skipped, "prompt_version": PROMPT_VERSION}


@router.post("/documents/{doc_id}/rerun")
def rerun(doc_id: int, effort: str | None = None, engine: str | None = None, model: str | None = None, session: Session = Depends(get_session)):
    d = session.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "no such document")
    if not _queue_rerun(d, effort=effort, engine=engine, model=model):
        raise HTTPException(409, "original bytes not kept; drop the file into Drive again")
    return {"accepted": True}



def _obs_key(o: Observation, fund_norm: dict[int, str]) -> tuple:
    return (fund_norm.get(o.fund_id, ""), o.share_class, o.metric, o.period_type, o.period_year, o.period_month, o.basis)


@router.get("/documents/{doc_id}/versions")
def versions(doc_id: int, session: Session = Depends(get_session)):
    d = session.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "no such document")
    q = select(Document).where(Document.drive_file_id == d.drive_file_id) if d.drive_file_id else select(Document).where(Document.source == d.source, Document.name == d.name)
    sibs = session.scalars(q.order_by(Document.created_at.desc())).all()
    fund_norm = {f.id: f.name_norm for f in session.scalars(select(Fund))}
    out = []
    for i, v in enumerate(sibs):
        vv = v.validation_json or {}
        entry = {"document_id": v.id, "created_at": v.created_at.isoformat(timespec="seconds"), "status": v.status, "model": v.model, "engine": v.engine,
                 "prompt_version": (v.usage_json or {}).get("prompt_version", ""), "cost_usd": v.cost_usd, "n_rows": vv.get("n_rows", 0), "n_facts": vv.get("n_facts", 0),
                 "is_current": v.is_current, "title": v.title, "diff": None}
        if i + 1 < len(sibs):
            prev = sibs[i + 1]
            cur_obs = {_obs_key(o, fund_norm): o.value for o in session.scalars(select(Observation).where(Observation.document_id == v.id))}
            prev_obs = {_obs_key(o, fund_norm): o.value for o in session.scalars(select(Observation).where(Observation.document_id == prev.id))}
            added = [k for k in cur_obs if k not in prev_obs]
            removed = [k for k in prev_obs if k not in cur_obs]
            changed = [(k, prev_obs[k], cur_obs[k]) for k in cur_obs if k in prev_obs and abs((cur_obs[k] or 0) - (prev_obs[k] or 0)) > 1e-9]
            fmt = lambda k: f"{k[0]}{(' ' + k[1]) if k[1] else ''} · {k[2]} · {k[4] or ''}{('-%02d' % k[5]) if k[5] else ''} {k[3]}".strip()
            entry["diff"] = {"added": [fmt(k) for k in added[:30]], "removed": [fmt(k) for k in removed[:30]],
                             "changed": [{"key": fmt(k), "before": a, "after": b} for k, a, b in changed[:30]],
                             "n_added": len(added), "n_removed": len(removed), "n_changed": len(changed)}
        out.append(entry)
    return {"versions": out}


@router.get("/funds/duplicates")
def fund_duplicates(session: Session = Depends(get_session)):
    """Pairs of funds that look like the same thing (name similarity or token containment)."""
    funds = session.scalars(select(Fund).order_by(Fund.name)).all()
    counts = dict(session.execute(select(Observation.fund_id, func.count()).group_by(Observation.fund_id)).all())
    pairs = []
    for i, a in enumerate(funds):
        ta = set(a.name_norm.split())
        for b in funds[i + 1:]:
            tb = set(b.name_norm.split())
            ratio = difflib.SequenceMatcher(None, a.name_norm, b.name_norm).ratio()
            contain = bool(ta and tb and (ta <= tb or tb <= ta)) and min(len(ta), len(tb)) >= 2
            if ratio >= 0.82 or contain:
                pairs.append({"score": round(max(ratio, 0.9 if contain else 0), 2),
                              "a": {"id": a.id, "name": a.name, "manager": a.manager, "n": counts.get(a.id, 0)},
                              "b": {"id": b.id, "name": b.name, "manager": b.manager, "n": counts.get(b.id, 0)}})
    pairs.sort(key=lambda p: -p["score"])
    return {"pairs": pairs[:40]}


class MergeIn(BaseModel):
    into: int


@router.post("/funds/{fund_id}/merge")
def merge_fund(fund_id: int, body: MergeIn, session: Session = Depends(get_session)):
    src, dst = session.get(Fund, fund_id), session.get(Fund, body.into)
    if src is None or dst is None or src.id == dst.id:
        raise HTTPException(400, "pick two different existing funds")
    n = session.execute(update(Observation).where(Observation.fund_id == src.id).values(fund_id=dst.id)).rowcount
    aliases = list(dst.aliases or [])
    for a in [src.name, *(src.aliases or [])]:
        if a and a not in aliases:
            aliases.append(a)
    dst.aliases = aliases
    if not dst.manager and src.manager:
        dst.manager = src.manager
    session.delete(src)
    session.commit()
    return {"merged_into": dst.id, "name": dst.name, "moved_observations": n, "aliases": aliases}


@router.get("/observations")
def observations(
    session: Session = Depends(get_session),
    fund_id: int | None = None, manager: str | None = None, metric: str | None = None, period_type: str | None = None,
    year: int | None = None, month: int | None = None, basis: str | None = None, q: str | None = None,
    date_from: date | None = None, date_to: date | None = None, limit: int = Query(500, le=5000), offset: int = 0,
):
    where, params = ["1=1"], {}
    if fund_id:
        where.append("fund_id = :fund_id"); params["fund_id"] = fund_id
    if manager:
        where.append("manager = :manager"); params["manager"] = manager
    if metric:
        where.append("metric = :metric"); params["metric"] = metric
    if period_type:
        where.append("period_type = :period_type"); params["period_type"] = period_type
    if year:
        where.append("period_year = :year"); params["year"] = year
    if month:
        where.append("period_month = :month"); params["month"] = month
    if basis:
        where.append("basis = :basis"); params["basis"] = basis
    if date_from:
        where.append("period_end >= :date_from"); params["date_from"] = date_from
    if date_to:
        where.append("period_end <= :date_to"); params["date_to"] = date_to
    if q:
        where.append("(LOWER(fund) LIKE :q OR LOWER(manager) LIKE :q OR LOWER(metric_label) LIKE :q OR LOWER(period_label) LIKE :q)"); params["q"] = f"%{q.lower()}%"
    sql = f"SELECT * FROM v_observations WHERE {' AND '.join(where)} ORDER BY fund, metric, period_end, period_label LIMIT :limit OFFSET :offset"
    params.update({"limit": limit, "offset": offset})
    res = session.execute(text(sql), params)
    cols = list(res.keys())
    rows = [dict(zip(cols, [v.isoformat() if isinstance(v, date) else v for v in r])) for r in res]
    total = session.execute(text(f"SELECT COUNT(*) FROM v_observations WHERE {' AND '.join(where)}"), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()
    return {"rows": rows, "total": total}


@router.get("/observations.csv")
def observations_csv(session: Session = Depends(get_session), **_):
    res = session.execute(text("SELECT * FROM v_observations ORDER BY fund, metric, period_end"))
    df = pd.DataFrame(res.fetchall(), columns=list(res.keys()))
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="observations.csv"'})


@router.get("/facts")
def facts(session: Session = Depends(get_session), q: str | None = None, document_id: int | None = None, limit: int = Query(500, le=5000)):
    where, params = ["1=1"], {"limit": limit}
    if document_id:
        where.append("document_id = :document_id"); params["document_id"] = document_id
    if q:
        where.append("(LOWER(subject) LIKE :q OR LOWER(attribute) LIKE :q OR LOWER(value_text) LIKE :q OR LOWER(document_name) LIKE :q)"); params["q"] = f"%{q.lower()}%"
    res = session.execute(text(f"SELECT * FROM v_facts WHERE {' AND '.join(where)} ORDER BY document_name, subject, attribute LIMIT :limit"), params)
    cols = list(res.keys())
    return {"rows": [dict(zip(cols, [v.isoformat() if isinstance(v, date) else v for v in r])) for r in res]}


@router.get("/funds")
def funds(session: Session = Depends(get_session)):
    rows = session.execute(
        select(Fund.id, Fund.name, Fund.manager, Fund.aliases, func.count(Observation.id), func.count(func.distinct(Observation.document_id)))
        .outerjoin(Observation, Observation.fund_id == Fund.id).group_by(Fund.id).order_by(Fund.name)
    ).all()
    return {"funds": [{"id": i, "name": n, "manager": m, "aliases": a or [], "n_observations": c, "n_documents": d} for i, n, m, a, c, d in rows]}


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    by_status = {s: n for s, n in session.execute(select(Document.status, func.count()).where(Document.is_current.is_(True)).group_by(Document.status))}
    n_obs = session.scalar(select(func.count()).select_from(Observation).join(Document, Document.id == Observation.document_id).where(Document.is_current.is_(True)))
    n_funds = session.scalar(select(func.count()).select_from(Fund))
    cost = session.scalar(select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)))
    managers = session.scalars(select(Fund.manager).where(Fund.manager != "").distinct()).all()   # one name per fund, not per document
    from ..llm import spend_today
    from ..config import settings as cfg
    outdated = sum(1 for d in session.scalars(select(Document).where(Document.is_current.is_(True), Document.status != "rejected")) if (d.usage_json or {}).get("prompt_version", "") != PROMPT_VERSION)
    return {"documents": by_status, "observations": n_obs, "funds": n_funds, "managers": sorted(managers), "cost_usd": round(cost or 0.0, 4),
            "today_cost_usd": round(spend_today(), 4), "daily_cost_cap_usd": cfg.daily_cost_cap_usd, "outdated_documents": outdated, "prompt_version": PROMPT_VERSION}
