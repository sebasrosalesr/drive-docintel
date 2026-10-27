from __future__ import annotations

import json
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..ask import agent, guard
from ..config import settings
from ..db import SessionLocal
from .deps import get_session

router = APIRouter(prefix="/api", tags=["ask"])


class Turn(BaseModel):
    role: str
    content: str = ""


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[Turn] = Field(default_factory=list)


@router.post("/ask")
def ask(body: AskIn, session: Session = Depends(get_session)):
    if not settings.llm_ready:
        raise HTTPException(503, "OPENROUTER_API_KEY is not set")
    try:
        return agent.ask(body.question, session=session, history=[t.model_dump() for t in body.history])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{type(exc).__name__}: {exc}"[:400]) from exc


@router.post("/ask/stream")
def ask_stream(body: AskIn):
    """NDJSON: {"type": "round"|"status"|"token"|"step"|"result"|"error", ...} one per line, as they happen."""
    if not settings.llm_ready:
        raise HTTPException(503, "OPENROUTER_API_KEY is not set")
    q: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            with SessionLocal() as s:
                res = agent.ask(body.question, session=s, on_event=q.put, history=[t.model_dump() for t in body.history])
            q.put({"type": "result", "result": res})
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "error", "detail": f"{type(exc).__name__}: {exc}"[:400]})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield json.dumps(ev, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/ask/suggestions")
def suggestions(session: Session = Depends(get_session)):
    """Questions worth asking, built from what is actually in the library (no model call)."""
    from sqlalchemy import func, select

    from ..models import Document, Observation
    docs = session.scalars(select(Document).where(Document.is_current.is_(True), Document.status != "failed").order_by(Document.id.desc())).all()
    n_month = session.execute(select(func.count()).select_from(Observation).where(Observation.metric == "return", Observation.period_type == "month")).scalar() or 0
    out: list[str] = []
    by_type: dict[str, list[Document]] = {}
    for d in docs:
        by_type.setdefault(d.doc_type, []).append(d)
    if n_month:
        out.append("Which fund had the best January return?")
    for d in by_type.get("offering", [])[:1]:
        out.append(f"What are the minimums and target sizes in “{(d.title or d.name)[:60]}”?")
    for d in by_type.get("portfolio_analysis", [])[:1]:
        out.append(f"Summarise the recommendation in “{(d.title or d.name)[:60]}”.")
    for d in by_type.get("term_sheet", [])[:1]:
        out.append(f"What does “{(d.title or d.name)[:60]}” offer, and until when?")
    if by_type.get("invoice"):
        out.append("How much did we pay each vendor, and when?")
    for d in (by_type.get("presentation", []) + by_type.get("brochure", []))[:1]:
        out.append(f"What is “{(d.title or d.name)[:60]}” about?")
    managers = sorted({d.manager for d in docs if d.manager})
    if len(managers) > 1:
        out.append(f"What documents do we have from {managers[0]}?")
    if len(docs) > 1:
        out.append("Which documents mention fees, and what are they?")
    return {"suggestions": out[:6]}


class SQLIn(BaseModel):
    sql: str


@router.post("/sql")
def run_sql(body: SQLIn):
    """The same guarded tool the model uses, exposed for the UI's audit panel."""
    try:
        cols, rows = guard.run(body.sql)
    except guard.SQLRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"{type(exc).__name__}: {exc}"[:300]) from exc
    return {"columns": cols, "rows": rows}
