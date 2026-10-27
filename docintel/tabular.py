"""Large spreadsheets: one model call returns a column MAPPING for the table; pandas-free code applies
it to every row, so cost does not grow with the number of rows."""
from __future__ import annotations

import calendar
import re
from typing import Any

from .normalize import _month_from_label, parse_date
from .schema import Extraction, FundHeader, Metric, Period, TableMapping

LARGE_TABLE_ROWS = 120      # above this, use the mapping path instead of sending the rows to the model
SAMPLE_ROWS = 12
_NUM = re.compile(r"^\(?\s*[-+]?\$?\s*[\d,]*\.?\d+\s*%?\s*\)?$")


def column_summaries(table: list[list[str]], header_row: int = 0) -> list[dict[str, Any]]:
    """Per column: header, a few distinct sample values, share of numeric cells. Fed to the model instead of the rows."""
    if not table:
        return []
    width = max(len(r) for r in table)
    body = table[header_row + 1:]
    out = []
    for c in range(width):
        vals = [r[c].strip() for r in body if c < len(r) and r[c].strip()]
        numeric = sum(1 for v in vals if _NUM.match(v))
        distinct = []
        for v in vals:
            if v not in distinct:
                distinct.append(v)
            if len(distinct) >= 5:
                break
        out.append({"index": c, "header": table[header_row][c] if c < len(table[header_row]) else "", "n_filled": len(vals),
                    "numeric_share": round(numeric / len(vals), 2) if vals else 0.0, "samples": distinct})
    return out


def parse_number(s: str) -> float | None:
    t = (s or "").strip()
    if not t or not _NUM.match(t):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("$", "").replace(",", "").replace("%", "").replace(" ", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def scale(v: float, unit: str) -> tuple[float, str]:
    if unit == "decimal":
        return round(v * 100, 6), "pct"
    if unit == "bps":
        return round(v / 100, 6), "pct"
    if unit in ("pct", "currency", "ratio"):
        return v, unit
    return v, "other"


def period_from_label(label: str, as_of: str) -> Period:
    d = parse_date(label)
    if d:
        return Period(type="month", label=label, start=d.replace(day=1).isoformat(), end=d.replace(day=calendar.monthrange(d.year, d.month)[1]).isoformat())
    y, m = _month_from_label(label)
    if m:
        if not y:
            ad = parse_date(as_of)
            y = ad.year if ad else None
        if y:
            return Period(type="month", label=label, start=f"{y}-{m:02d}-01", end=f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}")
        return Period(type="month", label=label, start="", end="")
    low = label.lower()
    if "ytd" in low:
        return Period(type="ytd", label=label, start="", end="")
    if re.fullmatch(r"(fy)?\s*\d{4}", low.strip()):
        yr = int(re.search(r"\d{4}", low).group(0))
        return Period(type="year", label=label, start=f"{yr}-01-01", end=f"{yr}-12-31")
    return Period(type="other", label=label, start="", end="")


def apply_mapping(table: list[list[str]], mp: TableMapping) -> tuple[Extraction, list[str]]:
    """Every data row → Metric rows. Returns the Extraction and a list of skipped-row notes."""
    header = mp.header_row if 0 <= mp.header_row < len(table) else 0
    head = table[header]
    rows = table[header + 1:]
    metrics: list[Metric] = []
    skipped: list[str] = []
    fund_names: list[str] = []

    def cell(r: list[str], i: int) -> str:
        return r[i].strip() if 0 <= i < len(r) else ""

    def fund_of(r: list[str]) -> str:
        name = cell(r, mp.fund_name_column) if mp.fund_name_column >= 0 else mp.fund_name_constant
        return name or mp.fund_name_constant or "Unnamed"

    for i, r in enumerate(rows, start=header + 2):   # 1-based row number in the file
        if not any(c.strip() for c in r):
            continue
        fund = fund_of(r)
        share = cell(r, mp.share_class_column) if mp.share_class_column >= 0 else ""
        evidence = f"row {i}: " + " | ".join(c.strip() for c in r if c.strip())[:150]
        if fund not in fund_names:
            fund_names.append(fund)
        if mp.layout == "wide":
            for pc in mp.period_columns:
                v = parse_number(cell(r, pc.column))
                if v is None:
                    continue
                val, unit = scale(v, mp.unit)
                metrics.append(Metric(fund_name=fund, share_class=share, metric=mp.metric, metric_label=(head[pc.column] if pc.column < len(head) else pc.label) or pc.label,
                                      period=period_from_label(pc.label or (head[pc.column] if pc.column < len(head) else ""), mp.as_of_date), value=val, unit=unit, annualized=False,
                                      basis=mp.basis, currency=mp.currency, evidence_text=evidence, page=1, confidence="high"))
        else:
            v = parse_number(cell(r, mp.value_column))
            if v is None:
                skipped.append(f"row {i}: no numeric value")
                continue
            label = cell(r, mp.date_column) if mp.date_column >= 0 else mp.as_of_date
            metric = mp.metric
            mlabel = cell(r, mp.metric_column) if mp.metric_column >= 0 else (head[mp.value_column] if mp.value_column < len(head) else mp.metric)
            if mp.metric_column >= 0:
                low = mlabel.lower()
                for key in ("benchmark", "aum", "nav", "expense", "mgmt", "management", "perf", "sharpe", "vol", "drawdown"):
                    if key in low:
                        metric = {"benchmark": "benchmark_return", "aum": "aum", "nav": "nav", "expense": "expense_ratio", "mgmt": "mgmt_fee", "management": "mgmt_fee",
                                  "perf": "perf_fee", "sharpe": "sharpe", "vol": "volatility", "drawdown": "max_drawdown"}[key]
                        break
            val, unit = scale(v, mp.unit)
            metrics.append(Metric(fund_name=fund, share_class=share, metric=metric, metric_label=mlabel or metric, period=period_from_label(label, mp.as_of_date),
                                  value=val, unit=unit, annualized=False, basis=mp.basis, currency=mp.currency, evidence_text=evidence, page=1, confidence="high"))
    as_of = mp.as_of_date
    if not parse_date(as_of):   # infer from the data: the latest period end in the file
        ends = [parse_date(m.period.end) for m in metrics if m.period.end]
        ends = [d for d in ends if d]
        if ends:
            as_of = max(ends).isoformat()
    ex = Extraction(
        doc_type=mp.doc_type, title=mp.title, summary=mp.summary, key_points=list(mp.key_points), manager=mp.manager, manager_evidence=mp.manager,
        as_of_date=as_of, as_of_evidence=as_of if as_of == mp.as_of_date else "latest period in the file", currency=mp.currency,
        funds=[FundHeader(name=n, share_class="", strategy="", evidence_text=n) for n in fund_names[:50]], metrics=metrics, facts=[],
        warnings=list(mp.warnings) + ([f"{len(skipped)} row(s) had no numeric value"] if skipped else []),
    )
    return ex, skipped
