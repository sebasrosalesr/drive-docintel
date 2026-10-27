import json

from conftest import canned_response, extraction, fact, metric

from docintel.ask import agent, registry
from docintel.pipeline import process_bytes


def _seed(session):
    ex = extraction(doc_type="offering", summary="A pipeline deck of private funds.", facts=[fact(ev="Minimum investment: $250,000")], metrics=[])
    doc = process_bytes(session, name="deck.txt", mime="text/plain", data=b"--- page 1 ---\nFund X overview\n--- page 2 ---\nMinimum investment: $250,000 for Fund X\n",
                        transport=lambda b: canned_response(ex), force=True)
    return doc


def test_digest_search_and_read(session):
    doc = _seed(session)
    text, n = registry.digest(session)
    assert f"doc:{doc.id}" in text and "offering" in text and n >= 1
    hits = registry.search(session, "minimum investment Fund X")
    assert hits and hits[0]["document_id"] == doc.id and "250,000" in hits[0]["snippet"]
    r = registry.read(session, doc.id, 2, 2)
    assert r["page_from"] == 2 and "250,000" in r["text"] and r["facts"][0]["attribute"] == "Minimum investment"
    assert registry.read(session, 999_999) is None


def test_agent_uses_search_and_read_and_cites_pages(session):
    doc = _seed(session)
    script = iter([
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_documents", "arguments": json.dumps({"query": "minimum investment"})}}]}}], "usage": {}},
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "read_document", "arguments": json.dumps({"document_id": doc.id, "page_from": 2, "page_to": 2})}}]}}], "usage": {}},
        {"choices": [{"message": {"content": f"The minimum is **$250,000** [doc:{doc.id} p.2] [fact:1]. Also [doc:4242 p.9]."}}], "usage": {}},
    ])
    events = []
    res = agent.ask("what is the minimum?", session=session, transport=lambda body: next(script), on_event=events.append,
                    history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    assert [s["tool"] for s in res["steps"]] == ["search_documents", "read_document"]
    assert res["cited_document_ids"] == [doc.id] and "doc:4242" in res["dropped_citations"]
    assert res["sources"][0]["document_id"] == doc.id and 2 in res["sources"][0]["pages"]
    assert any("Searching the documents" in e.get("text", "") for e in events if e["type"] == "status")
