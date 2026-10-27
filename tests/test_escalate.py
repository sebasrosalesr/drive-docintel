"""Send to engineering: without a webhook (the demo) nothing leaves and the reply
shows the message; with one, a single Slack-shaped POST goes out."""

import dataclasses

from conftest import canned_response, extraction, metric
from fastapi.testclient import TestClient

from docintel.api import data_routes
from docintel.config import settings
from docintel.main import app
from docintel.pipeline import process_bytes

client = TestClient(app)


def _flagged(session):
    d = process_bytes(session, name="odd.txt", mime="text/plain", data=b"Jan 2026 1.0", transport=lambda b: canned_response(extraction(metrics=[metric("Alpha Fund", 1.0, ev="Jan 2026 1.0")])), force=True)
    d.status = "needs_review"
    d.validation_json = {"flags": [{"code": "range", "msg": "a monthly return of 180% is outside the plausible range"}, {"code": "model_warning", "msg": "ignored"}]}
    session.commit()
    return d


def test_without_a_webhook_the_demo_only_says_what_it_would_send(session, monkeypatch):
    d = _flagged(session)
    monkeypatch.setattr(data_routes, "settings", dataclasses.replace(settings, escalation_webhook_url=""))
    r = client.post(f"/api/documents/{d.id}/escalate", json={"note": "second sheet has merged cells"})
    assert r.status_code == 200 and r.json()["sent"] is False
    text = r.json()["text"]
    assert "odd.txt" in text and "needs_review" in text and "180%" in text and "merged cells" in text and "ignored" not in text
    assert client.post("/api/documents/999999/escalate", json={}).status_code == 404


def test_with_a_webhook_one_post_goes_out(session, monkeypatch):
    d = _flagged(session)
    monkeypatch.setattr(data_routes, "settings", dataclasses.replace(settings, escalation_webhook_url="https://hooks.example/abc"))
    sent = []

    class _R:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(data_routes.httpx, "post", lambda url, json, timeout: sent.append((url, json)) or _R())
    r = client.post(f"/api/documents/{d.id}/escalate", json={})
    assert r.json()["sent"] is True
    assert sent[0][0] == "https://hooks.example/abc" and sent[0][1]["text"].startswith("[DocIntel]")
