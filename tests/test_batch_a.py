import email
import json
from email.message import EmailMessage

from conftest import canned_response, extraction, metric
from fastapi.testclient import TestClient
from sqlalchemy import select

from docintel.main import app
from docintel.models import Document, Fund, Observation
from docintel.pipeline import process_bytes


def test_fund_merge_and_duplicates(session):
    ex1 = extraction(metrics=[metric("Alpha Growth Fund LP", 1.0, ev="Jan 2026 1.0")])
    ex2 = extraction(metrics=[metric("Alpha Growth Opportunities Fund", 2.0, label="Feb 2026", start="2026-02-01", end="2026-02-28", ev="Feb 2026 2.0")])
    process_bytes(session, name="a1.txt", mime="text/plain", data=b"Jan 2026 1.0", transport=lambda b: canned_response(ex1), force=True)
    process_bytes(session, name="a2.txt", mime="text/plain", data=b"Feb 2026 2.0", transport=lambda b: canned_response(ex2), force=True)
    client = TestClient(app)
    pairs = client.get("/api/funds/duplicates").json()["pairs"]
    names = {(p["a"]["name"], p["b"]["name"]) for p in pairs}
    assert any("Alpha Growth" in a and "Alpha Growth" in b for a, b in names)
    a = session.scalar(select(Fund).where(Fund.name == "Alpha Growth Fund LP"))
    b = session.scalar(select(Fund).where(Fund.name == "Alpha Growth Opportunities Fund"))
    r = client.post(f"/api/funds/{b.id}/merge", json={"into": a.id}).json()
    assert r["moved_observations"] == 1 and "Alpha Growth Opportunities Fund" in r["aliases"]
    from docintel.db import SessionLocal
    with SessionLocal() as fresh:
        assert fresh.scalar(select(Fund).where(Fund.id == b.id)) is None
        assert fresh.scalar(select(Observation).where(Observation.fund_id == a.id, Observation.value == 2.0)) is not None


def test_versions_diff(session):
    v1 = extraction(metrics=[metric("Beta Fund", 1.0, ev="Jan 2026 1.0"), metric("Beta Fund", 3.0, label="Mar 2026", start="2026-03-01", end="2026-03-31", ev="Mar 2026 3.0")])
    v2 = extraction(metrics=[metric("Beta Fund", 1.5, ev="Jan 2026 1.5"), metric("Beta Fund", 2.0, label="Feb 2026", start="2026-02-01", end="2026-02-28", ev="Feb 2026 2.0")])
    d1 = process_bytes(session, name="beta.txt", mime="text/plain", data=b"Jan 2026 1.0 Mar 2026 3.0", transport=lambda b: canned_response(v1), force=True)
    d2 = process_bytes(session, name="beta.txt", mime="text/plain", data=b"Jan 2026 1.5 Feb 2026 2.0", transport=lambda b: canned_response(v2), force=True)
    vs = TestClient(app).get(f"/api/documents/{d2.id}/versions").json()["versions"]
    assert [v["document_id"] for v in vs][:2] == [d2.id, d1.id] and vs[0]["is_current"] and not vs[1]["is_current"]
    diff = vs[0]["diff"]
    assert diff["n_changed"] == 1 and diff["changed"][0]["before"] == 1.0 and diff["changed"][0]["after"] == 1.5
    assert diff["n_added"] == 1 and diff["n_removed"] == 1


def test_email_attachments_become_child_documents(session):
    msg = EmailMessage()
    msg["From"] = "ir@example.com"; msg["To"] = "me@example.com"; msg["Subject"] = "Monthly update"; msg["Date"] = "Mon, 05 Oct 2026 10:00:00 +0000"
    msg.set_content("Please find the factsheet attached. September net return +1.20%.")
    msg.add_attachment(b"month,fund,return\nSep 2026,Gamma Fund,1.2\n", maintype="text", subtype="csv", filename="gamma.csv")
    msg.add_attachment(b"\x00\x01binary", maintype="application", subtype="octet-stream", filename="blob.bin")
    calls = []

    def transport(body):
        calls.append(body)
        return canned_response(extraction(doc_type="email_update", metrics=[metric("Gamma Fund", 1.2, label="Sep 2026", start="2026-09-01", end="2026-09-30", ev="1.2")]))

    parent = process_bytes(session, name="update.eml", mime="message/rfc822", data=msg.as_bytes(), transport=transport, force=True)
    child = session.scalar(select(Document).where(Document.parent_document_id == parent.id))
    assert child is not None and child.name == "update.eml » gamma.csv" and child.status in ("done", "needs_review")
    assert len(calls) == 2   # the email and the csv; the binary attachment was skipped


def test_cost_cap_blocks_calls(monkeypatch):
    from docintel import llm
    from docintel.config import settings
    monkeypatch.setattr(llm, "spend_today", lambda: 5.0)
    monkeypatch.setattr(settings.__class__, "daily_cost_cap_usd", property(lambda self: 1.0), raising=False)
    try:
        llm.check_cost_cap()
        assert False, "should have raised"
    except llm.CostCapReached as exc:
        assert "cap reached" in str(exc).lower()


def test_app_password_gate(monkeypatch):
    from docintel.config import settings
    monkeypatch.setattr(settings.__class__, "app_password", property(lambda self: "s3cret"), raising=False)
    client = TestClient(app)
    assert client.get("/api/stats").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/login", json={"password": "s3cret"})
    assert r.status_code == 200 and client.cookies.get("docintel_app")
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/me").json()["auth_required"] is True
