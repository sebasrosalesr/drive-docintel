from datetime import date

import pytest

from docintel.normalize import norm_fund_name, page_texts, period_fields, verify_evidence
from docintel.schema import Period


@pytest.mark.parametrize("a,b", [
    ("Northwind Global Macro Fund LP", "Northwind Global Macro Fund, L.P. - Class A"),
    ("Harbor Point Credit Opportunities Fund", "Harbor Point Credit Opportunities (Class I Shares)"),
    ("Sable Ridge Equity Long/Short", "SABLE RIDGE EQUITY LONG SHORT LTD"),
])
def test_fund_name_variants_collapse(a, b):
    assert norm_fund_name(a) == norm_fund_name(b)


def test_different_funds_stay_apart():
    assert norm_fund_name("Northwind Global Macro") != norm_fund_name("Northwind Credit")


ASOF = date(2026, 9, 30)


def test_month_without_year_uses_as_of_year_and_wraps():
    jan = period_fields(Period(type="month", label="Jan", start="", end=""), ASOF)
    assert (jan["period_year"], jan["period_month"], jan["period_end"]) == (2026, 1, date(2026, 1, 31))
    octo = period_fields(Period(type="month", label="October", start="", end=""), ASOF)
    assert (octo["period_year"], octo["period_month"]) == (2025, 10)


def test_explicit_dates_win():
    p = period_fields(Period(type="month", label="whatever", start="2025-01-01", end="2025-01-31"), ASOF)
    assert (p["period_year"], p["period_month"]) == (2025, 1)


def test_ytd_and_trailing_periods_anchor_on_as_of():
    ytd = period_fields(Period(type="ytd", label="YTD", start="", end=""), ASOF)
    assert ytd["period_start"] == date(2026, 1, 1) and ytd["period_end"] == ASOF and ytd["period_year"] == 2026
    three = period_fields(Period(type="3y", label="3Y (ann.)", start="", end=""), ASOF)
    assert three["period_end"] == ASOF


def test_evidence_verification_tolerates_layout_noise():
    text = "Class A\n2.14\n1.35\nManagement fee\n1.50% p.a.\nMax drawdown −4.9 %"
    assert verify_evidence("Class A 2.14", text)[0]
    assert verify_evidence("Management fee 1.50 % p.a.", text)[0]
    assert verify_evidence("Max drawdown -4.9%", text)[0]
    ok, note = verify_evidence("Performance fee 20%", text)
    assert not ok and note == "not-found"
    assert verify_evidence("anything", text, scanned=True) == (False, "scanned")


def test_reflowed_table_rows_verify_by_numbers_and_page():
    text = "--- page 1 ---\nIntro\n--- page 2 ---\nHarbor Fund\nJan\n0.92\nFeb\n1.10\n--- page 3 ---\n"
    pages = page_texts(text)
    assert set(pages) == {1, 2, 3}
    ok, note = verify_evidence("Harbor Fund | Jan | 0.92 | Feb | 1.10", text, page=2, pages=pages)
    assert ok and note in ("numbers", "exact") or note.startswith("fuzzy")
    assert verify_evidence("Harbor Fund Jan 0.92", text, page=3, pages=pages) == (False, "image-page")
    assert verify_evidence("Totally different 55.5 77.7", text, page=2, pages=pages)[0] is False


def test_ellipsis_joined_evidence_verifies_piecewise():
    text = "--- page 3 ---\nCO-INVESTS\nSelective co-investments alongside managers\n$2M+ typical check size\n"
    pages = page_texts(text)
    ok, note = verify_evidence("CO-INVESTS ... $2M+ typical check size", text, page=3, pages=pages)
    assert ok and note == "pieces"
    assert verify_evidence("CO-INVESTS ... $9M+ typical check size", text, page=3, pages=pages)[0] is False
