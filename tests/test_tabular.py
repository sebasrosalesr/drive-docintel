import json

from conftest import canned_response

from docintel.pipeline import process_bytes
from docintel.schema import TableMapping
from docintel.tabular import apply_mapping, column_summaries, parse_number


def mapping(**kw):
    base = {"layout": "long", "header_row": 0, "fund_name_column": 1, "fund_name_constant": "", "share_class_column": -1, "date_column": 0, "period_columns": [],
            "value_column": 2, "metric_column": -1, "metric": "return", "unit": "pct", "basis": "net", "doc_type": "performance_report", "title": "Big export",
            "summary": "A long export of monthly net returns.", "key_points": ["500 rows"], "manager": "Northwind", "as_of_date": "2026-09-30", "currency": "USD", "warnings": []}
    base.update(kw)
    return base


def test_parse_number_and_summaries():
    assert parse_number("(1.25)") == -1.25 and parse_number("2.14%") == 2.14 and parse_number("$1,200.50") == 1200.5 and parse_number("n/a") is None
    table = [["date", "fund", "ret"], ["2026-01-31", "A", "1.0"], ["2026-02-28", "A", "x"]]
    cs = column_summaries(table)
    assert cs[2]["numeric_share"] == 0.5 and cs[1]["samples"] == ["A"]


def test_long_layout_maps_every_row_without_sending_them(session):
    rows = ["date,fund,net_return_pct"] + [f"{2000 + i // 12}-{i % 12 + 1:02d}-28,Northwind Fund,{(i % 7) - 3}.{i % 10}" for i in range(500)]
    data = ("\n".join(rows) + "\n").encode()
    sent = []

    def transport(body):
        sent.append(body)
        return canned_response(mapping())

    doc = process_bytes(session, name="big_long.csv", mime="text/csv", data=data, transport=transport, force=True)
    assert len(sent) == 1 and "SAMPLE_ROWS" in sent[0]["messages"][1]["content"][0]["text"]
    assert "2041-" not in sent[0]["messages"][1]["content"][0]["text"]   # late rows never left the machine
    assert doc.engine == "table-mapping" and doc.validation_json["n_rows"] == 500 and doc.status in ("done", "needs_review")


def test_wide_layout_scales_decimals():
    table = [["Fund", "Jan-26", "Feb-26", "YTD"], ["Alpha", "0.0214", "(0.0050)", "0.0163"], ["", "", "", ""]]
    mp = TableMapping.model_validate(mapping(layout="wide", fund_name_column=0, date_column=-1, value_column=-1, unit="decimal",
                                             period_columns=[{"column": 1, "label": "Jan-26"}, {"column": 2, "label": "Feb-26"}, {"column": 3, "label": "YTD"}]))
    ex, skipped = apply_mapping(table, mp)
    vals = {(m.period.label, m.period.type): m.value for m in ex.metrics}
    assert vals[("Jan-26", "month")] == 2.14 and vals[("Feb-26", "month")] == -0.5 and vals[("YTD", "ytd")] == 1.63
    assert ex.metrics[0].period.start == "2026-01-01" and ex.metrics[0].unit == "pct" and not skipped
