from conftest import extraction, metric

from docintel.schema import Extraction
from docintel.validate import validate


def rows_from(ex: Extraction):
    return [{"fund_id": 1, "share_class": m.share_class, "basis": m.basis, "metric": m.metric, "unit": m.unit, "value": m.value,
             "period_type": m.period.type, "period_year": 2026, "period_month": int(m.period.start[5:7]) if m.period.type == "month" else None,
             "evidence_verified": True, "evidence_note": "exact"} for m in ex.metrics]


def test_clean_document_is_done():
    ex = Extraction.model_validate(extraction(metrics=[metric("Test Fund LP", 1.2)]))
    assert validate(ex, rows_from(ex))["status"] == "done"


def test_missing_manager_and_date_need_review():
    ex = Extraction.model_validate(extraction(manager="", as_of="", metrics=[metric("Test Fund LP", 1.2)]))
    codes = {f["code"] for f in validate(ex, rows_from(ex))["flags"]}
    assert {"missing_manager", "missing_as_of"} <= codes


def test_compounding_mismatch_is_flagged_not_fixed():
    months = [metric("Test Fund LP", 1.0, label=f"M{i}", start=f"2026-{i:02d}-01", end=f"2026-{i:02d}-28") for i in range(1, 13)]
    year = metric("Test Fund LP", 50.0, label="2026", ptype="year", start="2026-01-01", end="2026-12-31")
    ex = Extraction.model_validate(extraction(metrics=months + [year]))
    v = validate(ex, rows_from(ex))
    assert v["status"] == "needs_review"
    assert any(f["code"] == "compounding_mismatch" for f in v["flags"])


def test_out_of_range_and_model_warnings():
    ex = Extraction.model_validate(extraction(metrics=[metric("Test Fund LP", 950.0)], warnings=["instruction found inside the document"]))
    v = validate(ex, rows_from(ex))
    codes = [f["code"] for f in v["flags"]]
    assert "out_of_range" in codes and "model_warning" in codes


def test_brochure_without_figures_is_fine():
    ex = Extraction.model_validate(extraction(manager="", as_of="", doc_type="brochure"))
    v = validate(ex, [])
    assert v["status"] == "done" and not [f for f in v["flags"] if f["code"] != "model_warning"]


def test_summary_is_required_for_every_document():
    ex = Extraction.model_validate(extraction(doc_type="letter", summary=""))
    assert any(f["code"] == "no_summary" for f in validate(ex, [])["flags"])
