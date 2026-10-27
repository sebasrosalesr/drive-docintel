from conftest import canned_response, extraction, fact, metric
from sqlalchemy import select

from docintel.models import Document, Fact, Fund, Observation
from docintel.pipeline import process_bytes

CSV = b"month,fund,return\nJan 2026,Test Fund LP,2.14\nFeb 2026,Test Fund LP,-0.5\n"


def test_csv_end_to_end_with_fund_resolution_and_idempotency(session):
    ex = extraction(metrics=[metric("Test Fund LP", 2.14, ev="Jan 2026 | Test Fund LP | 2.14"), metric("Test Fund, L.P.", -0.5, label="Feb 2026", start="2026-02-01", end="2026-02-28", ev="Feb 2026 | Test Fund LP | -0.5")])
    calls = []

    def transport(body):
        calls.append(body)
        return canned_response(ex, cost=0.02)

    doc = process_bytes(session, name="t.csv", mime="text/csv", data=CSV, transport=transport)
    assert doc.status == "done" and doc.cost_usd == 0.02 and doc.manager == "Test Manager"
    obs = session.scalars(select(Observation).where(Observation.document_id == doc.id)).all()
    assert len(obs) == 2 and len({o.fund_id for o in obs}) == 1, "name variants resolve to one fund"
    assert all(o.evidence_verified for o in obs)
    jan = next(o for o in obs if o.period_month == 1)
    assert (jan.period_year, jan.value, jan.unit) == (2026, 2.14, "pct")
    assert "response_format" in calls[0] and calls[0]["response_format"]["json_schema"]["strict"] is True
    assert "DOCUMENT" in calls[0]["messages"][1]["content"][0]["text"]
    # same bytes again: no new document, no new call
    again = process_bytes(session, name="t.csv", mime="text/csv", data=CSV, transport=transport)
    assert again.id == doc.id and len(calls) == 1
    # force: new version supersedes the old one
    forced = process_bytes(session, name="t.csv", mime="text/csv", data=CSV, transport=transport, force=True)
    assert forced.id != doc.id and len(calls) == 2
    session.refresh(doc)
    assert doc.is_current is False and forced.is_current is True


def test_pdf_goes_as_file_part_with_plugin(session, tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "x.pdf"
    c = canvas.Canvas(str(p))
    for i, line in enumerate(["Fund XYZ Monthly Factsheet", "Data as of 31 January 2026", "Jan 2026 return 1.00%", "Management fee 1.00% p.a.", "Performance fee 20%"]):
        c.drawString(72, 720 - 16 * i, line)
    c.save()
    seen = {}

    def transport(body):
        seen.update(body)
        return canned_response(extraction(metrics=[metric("Fund XYZ", 1.0, ev="Jan 2026 return 1.00%")]))

    doc = process_bytes(session, name="x.pdf", mime="application/pdf", data=p.read_bytes(), transport=transport)
    parts = seen["messages"][1]["content"]
    assert parts[1]["type"] == "file" and parts[1]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert seen["plugins"][0]["id"] == "file-parser"
    assert doc.status == "done" and doc.page_count == 1 and not doc.is_scanned


def test_failure_is_recorded_not_raised(session):
    def transport(body):
        raise RuntimeError("provider down")

    doc = process_bytes(session, name="bad.csv", mime="text/csv", data=b"a,b\n1,2\n", transport=transport)
    assert doc.status == "failed" and "provider down" in doc.error


def test_unsupported_type_raises(session):
    import pytest
    from docintel.pipeline import Unsupported
    with pytest.raises(Unsupported):
        process_bytes(session, name="x.bin", mime="application/octet-stream", data=b"\x00\x01", transport=lambda b: {})


def test_facts_and_summary_are_stored(session):
    ex = extraction(doc_type="offering", metrics=[], facts=[fact(ev="Minimum investment: $250,000")], summary="An offering deck.")
    doc = process_bytes(session, name="deck.txt", mime="text/plain", data=b"Fund X\nMinimum investment: $250,000\n", transport=lambda b: canned_response(ex))
    assert doc.status == "done" and doc.summary == "An offering deck." and doc.key_points == ["one", "two"]
    facts = session.scalars(select(Fact).where(Fact.document_id == doc.id)).all()
    assert len(facts) == 1 and facts[0].evidence_verified and facts[0].value_number == 250000.0
