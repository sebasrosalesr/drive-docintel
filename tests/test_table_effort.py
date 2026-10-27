"""Spreadsheets and CSVs are read with the lighter table effort; prose keeps the
house effort; an explicit, different effort is honoured. The transport sees the
request body, so the effort is read off the wire."""

from conftest import canned_response, extraction, metric
from docintel.config import settings
from docintel.pipeline import process_bytes


def _run(session, name, mime, data, effort=None):
    seen = {}

    def transport(body):
        seen["effort"] = body.get("reasoning", {}).get("effort")
        return canned_response(extraction([metric("Alpha Fund", 1.0)]))

    process_bytes(session, name=name, mime=mime, data=data, transport=transport, force=True, effort=effort)
    return seen["effort"]


def test_a_csv_gets_the_table_effort_and_prose_the_house_effort(session):
    assert settings.table_reasoning_effort == "low" and settings.reasoning_effort == "medium"
    assert _run(session, "returns.csv", "text/csv", b"month,fund,return\nJan 2026,Alpha Fund,1.0\n") == "low"
    assert _run(session, "note.txt", "text/plain", b"Alpha Fund returned 1.0% in Jan 2026") == "medium"


def test_an_explicit_different_effort_on_a_table_is_honoured(session):
    assert _run(session, "returns.csv", "text/csv", b"month,fund,return\nJan 2026,Alpha Fund,1.0\n", effort="high") == "high"
    assert _run(session, "returns.csv", "text/csv", b"month,fund,return\nJan 2026,Alpha Fund,1.0\n", effort="medium") == "low"
