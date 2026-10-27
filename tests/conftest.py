"""A throwaway SQLite database per test session; no network anywhere."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="docintel-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")   # set DATABASE_URL to run the suite against Postgres
os.environ["DATA_DIR"] = _tmp
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ.setdefault("APP_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

import pytest  # noqa: E402

from docintel.db import SessionLocal, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()


@pytest.fixture
def session():
    with SessionLocal() as s:
        yield s


def canned_response(extraction: dict, cost: float = 0.01) -> dict:
    return {"model": "fake/model", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(extraction)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": cost}}


def metric(fund, value, label="Jan 2026", ptype="month", start="2026-01-01", end="2026-01-31", metric="return", unit="pct", cls="", basis="net", ev=None):
    return {"fund_name": fund, "share_class": cls, "metric": metric, "metric_label": "Net return", "period": {"type": ptype, "label": label, "start": start, "end": end},
            "value": value, "unit": unit, "annualized": False, "basis": basis, "currency": "USD", "evidence_text": ev if ev is not None else f"{label} {value}", "page": 1, "confidence": "high"}


def fact(attribute="Minimum investment", value_text="$250,000", value_number=250000.0, unit="currency", subject="Test Fund LP", ev=None):
    return {"subject": subject, "attribute": attribute, "value_text": value_text, "value_number": value_number, "unit": unit, "currency": "USD",
            "as_of": "", "evidence_text": ev or f"{attribute}: {value_text}", "page": 1, "confidence": "high"}


def extraction(manager="Test Manager", as_of="2026-09-30", metrics=None, doc_type="factsheet", warnings=None, facts=None, summary="A test document."):
    return {"doc_type": doc_type, "title": "Test document", "summary": summary, "key_points": ["one", "two"],
            "manager": manager, "manager_evidence": manager, "as_of_date": as_of, "as_of_evidence": as_of, "currency": "USD",
            "funds": [{"name": "Test Fund LP", "share_class": "", "strategy": "", "evidence_text": "Test Fund LP"}], "metrics": metrics or [],
            "facts": facts or [], "warnings": warnings or []}
