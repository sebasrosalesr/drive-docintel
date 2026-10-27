"""The document registry as the chat sees it: a digest of what is in the library, a passage search
across titles / summaries / key points / facts / page text, and a page reader.

Scoring is a small term-overlap ranker in Python (the library is tens of documents, not millions);
it needs no extension on SQLite or Postgres.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Document, Fact, Observation
from ..normalize import page_texts

MAX_DIGEST_DOCS = 80
MAX_READ_CHARS = 14_000
_TOKEN = re.compile(r"[a-z0-9][a-z0-9.\-%$]*")
STOP = {"the", "and", "for", "with", "that", "this", "from", "what", "which", "does", "about", "are", "was", "were", "has", "have",
        "how", "much", "many", "any", "all", "its", "our", "your", "their", "into", "per", "say", "says", "tell", "show", "list", "give"}


def tokens(s: str) -> list[str]:
    return [t for t in _TOKEN.findall((s or "").lower()) if len(t) >= 2 and t not in STOP]


def digest(session: Session) -> tuple[str, int]:
    """One line per current document for the system prompt. Returns (text, count)."""
    figs = dict(session.execute(select(Observation.document_id, func.count()).group_by(Observation.document_id)).all())
    facts = dict(session.execute(select(Fact.document_id, func.count()).group_by(Fact.document_id)).all())
    docs = session.scalars(select(Document).where(Document.is_current.is_(True), Document.status != "failed").order_by(Document.as_of_date.desc().nullslast(), Document.id.desc())).all()
    lines = []
    for d in docs[:MAX_DIGEST_DOCS]:
        lines.append(f"- doc:{d.id} | {d.title or d.name} | {d.doc_type} | {d.manager or 'unknown source'} | as of {d.as_of_date or 'n/a'} | "
                     f"{d.page_count} pp | {figs.get(d.id, 0)} figures, {facts.get(d.id, 0)} facts | file: {d.name}")
    if len(docs) > MAX_DIGEST_DOCS:
        lines.append(f"- … and {len(docs) - MAX_DIGEST_DOCS} more; use search_documents to find them")
    return "\n".join(lines), len(docs)


def _snippet(text: str, terms: list[str], width: int = 420) -> str:
    low = text.lower()
    best = -1
    for t in terms:
        i = low.find(t)
        if i >= 0 and (best < 0 or i < best):
            best = i
    start = max(0, (best if best >= 0 else 0) - width // 3)
    snip = re.sub(r"\s+", " ", text[start:start + width]).strip()
    return ("…" if start > 0 else "") + snip + ("…" if start + width < len(text) else "")


def search(session: Session, query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Top passages across the library: (document, page, snippet, score). Page 0 = the document's own summary/facts."""
    terms = tokens(query)
    if not terms:
        return []
    docs = session.scalars(select(Document).where(Document.is_current.is_(True), Document.status != "failed")).all()
    fact_text: dict[int, list[str]] = defaultdict(list)
    for f in session.scalars(select(Fact)):
        fact_text[f.document_id].append(f"{f.subject} {f.attribute}: {f.value_text}")
    hits: list[tuple[float, dict[str, Any]]] = []
    df: dict[str, int] = defaultdict(int)
    corpora: list[tuple[Document, int, str, float]] = []
    for d in docs:
        head = " ".join([d.title or "", d.summary or "", " ".join(d.key_points or []), " ".join(fact_text.get(d.id, []))])
        corpora.append((d, 0, head, 1.6))
        for pno, ptext in page_texts(d.raw_text or "").items():
            if ptext.strip():
                corpora.append((d, pno, ptext, 1.0))
    for _, _, text, _ in corpora:
        low = text.lower()
        for t in set(terms):
            if t in low:
                df[t] += 1
    n = max(1, len(corpora))
    for d, pno, text, boost in corpora:
        low = text.lower()
        score = 0.0
        for t in terms:
            c = low.count(t)
            if c:
                score += (1 + math.log(c)) * math.log(1 + n / (1 + df[t]))
        if score > 0:
            hits.append((score * boost, {"document_id": d.id, "title": d.title or d.name, "doc_type": d.doc_type, "manager": d.manager,
                                         "as_of": d.as_of_date.isoformat() if d.as_of_date else None, "page": pno, "snippet": _snippet(text, terms)}))
    hits.sort(key=lambda h: -h[0])
    out, seen = [], defaultdict(int)
    for score, h in hits:
        if seen[h["document_id"]] >= 3:   # at most 3 passages per document so one deck can't crowd out the rest
            continue
        seen[h["document_id"]] += 1
        h["score"] = round(score, 2)
        out.append(h)
        if len(out) >= limit:
            break
    return out


def read(session: Session, document_id: int, page_from: int = 1, page_to: int | None = None) -> dict[str, Any] | None:
    d = session.get(Document, document_id)
    if d is None or not d.is_current:
        return None
    pages = page_texts(d.raw_text or "")
    if not pages and d.raw_text:
        pages = {1: d.raw_text}
    last = max(pages) if pages else 0
    page_to = min(page_to or page_from + 5, last) if last else 0
    page_from = max(1, page_from)
    chunks, used = [], 0
    for p in range(page_from, page_to + 1):
        t = pages.get(p, "")
        if not t.strip():
            chunks.append(f"[page {p}: no text layer]")
            continue
        t = re.sub(r"[ \t]+", " ", t).strip()
        if used + len(t) > MAX_READ_CHARS:
            chunks.append(f"[page {p}: truncated]")
            t = t[: max(0, MAX_READ_CHARS - used)]
        used += len(t)
        chunks.append(f"--- page {p} ---\n{t}")
        if used >= MAX_READ_CHARS:
            break
    facts = session.scalars(select(Fact).where(Fact.document_id == d.id).order_by(Fact.id).limit(60)).all()
    figs = session.execute(select(func.count()).select_from(Observation).where(Observation.document_id == d.id)).scalar()
    return {
        "document_id": d.id, "title": d.title or d.name, "file": d.name, "doc_type": d.doc_type, "manager": d.manager,
        "as_of": d.as_of_date.isoformat() if d.as_of_date else None, "pages": last, "summary": d.summary, "key_points": d.key_points or [],
        "facts": [{"fact_id": f.id, "subject": f.subject, "attribute": f.attribute, "value": f.value_text, "page": f.page} for f in facts],
        "n_figures": figs, "text": "\n".join(chunks), "page_from": page_from, "page_to": page_to,
    }
