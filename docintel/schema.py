"""The one extraction schema every document is read into.

Every field is required (sentinels instead of Optional): Anthropic strict schemas cap
optional and union-typed parameters, and a fixed shape is easier to validate and store.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocType = Literal["factsheet", "statement", "performance_report", "email_update", "portfolio_analysis", "offering",
                  "term_sheet", "brochure", "letter", "presentation", "agreement", "invoice", "other"]
PERFORMANCE_TYPES = {"factsheet", "statement", "performance_report", "email_update", "portfolio_analysis"}
FactUnit = Literal["pct", "currency", "ratio", "multiple", "months", "years", "count", "date", "text", "other"]
MetricName = Literal["return", "benchmark_return", "aum", "nav", "expense_ratio", "mgmt_fee",
                     "perf_fee", "sharpe", "volatility", "max_drawdown", "other"]
PeriodType = Literal["month", "quarter", "ytd", "year", "1y", "3y", "5y", "since_inception", "point", "other"]
Unit = Literal["pct", "currency", "ratio", "multiple", "other"]
Basis = Literal["net", "gross", "unknown"]
Confidence = Literal["high", "medium", "low"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Period(Strict):
    type: PeriodType
    label: str = Field(description="Exactly as printed, e.g. 'Jan 2026', 'YTD', '3Y (ann.)'")
    start: str = Field(description="YYYY-MM-DD or empty string")
    end: str = Field(description="YYYY-MM-DD or empty string")


class Metric(Strict):
    fund_name: str
    share_class: str = Field(description="Empty string when the document has no share classes")
    metric: MetricName
    metric_label: str = Field(description="The label as printed, e.g. 'Net return', 'TER', 'Fund AUM'")
    period: Period
    value: float
    unit: Unit
    annualized: bool
    basis: Basis
    currency: str = Field(description="ISO code or empty string")
    evidence_text: str = Field(description="Verbatim fragment (<=160 chars) containing the value")
    page: int = Field(description="1-based page, 0 if unknown")
    confidence: Confidence


class FundHeader(Strict):
    name: str
    share_class: str
    strategy: str
    evidence_text: str


class Fact(Strict):
    """A concrete statement that is not a performance figure: a term, a size, a rate, a date, a condition."""
    subject: str = Field(description="What the fact is about: a fund, product, account or firm; '' for the document as a whole")
    attribute: str = Field(description="Plain label, e.g. 'Minimum investment', 'Target fund size', 'APY', 'Final close', 'Lock-up', 'Strategy'")
    value_text: str = Field(description="The value as printed")
    value_number: float = Field(description="The value as a number when it is one (percent points for pct, full amount for currency), else 0")
    unit: FactUnit
    currency: str
    as_of: str = Field(description="YYYY-MM-DD or empty string")
    evidence_text: str
    page: int
    confidence: Confidence


class Extraction(Strict):
    doc_type: DocType
    title: str = Field(description="A short plain-English title for the document")
    summary: str = Field(description="2-4 sentences in plain English for a non-technical reader: what this document is, who it is from, what it says")
    key_points: list[str] = Field(description="Up to 6 short bullets a busy reader needs")
    manager: str
    manager_evidence: str
    as_of_date: str = Field(description="YYYY-MM-DD or empty string")
    as_of_evidence: str
    currency: str
    funds: list[FundHeader]
    metrics: list[Metric]
    facts: list[Fact]
    warnings: list[str]


def extraction_json_schema() -> dict:
    return Extraction.model_json_schema()


def count_optional_and_union(schema: dict) -> tuple[int, int]:
    """How many properties are optional (not in required) or union-typed (anyOf). Kept under
    Anthropic's strict-mode caps (24 / 16) by a unit test."""
    optional = union = 0

    def walk(node: dict) -> None:
        nonlocal optional, union
        props = node.get("properties") or {}
        required = set(node.get("required") or [])
        for name, prop in props.items():
            if name not in required:
                optional += 1
            if "anyOf" in prop or "oneOf" in prop:
                union += 1
            walk(prop)
            if "items" in prop and isinstance(prop["items"], dict):
                walk(prop["items"])
        for d in (node.get("$defs") or {}).values():
            walk(d)

    walk(schema)
    return optional, union


# ---------- large tables: the model returns a mapping, code applies it to every row ----------
class PeriodColumn(Strict):
    column: int = Field(description="0-based column index")
    label: str = Field(description="The period as printed in the header, e.g. 'Jan-26', 'YTD'")


class TableMapping(Strict):
    layout: Literal["wide", "long", "unknown"] = Field(description="wide: one column per period; long: one row per observation")
    header_row: int = Field(description="0-based index of the header row in the sample")
    fund_name_column: int = Field(description="0-based column with the fund/portfolio name, or -1")
    fund_name_constant: str = Field(description="The fund name when there is no column, else ''")
    share_class_column: int
    date_column: int = Field(description="long layout: column with the period/date, or -1")
    period_columns: list[PeriodColumn] = Field(description="wide layout: the period columns")
    value_column: int = Field(description="long layout: column with the value, or -1")
    metric_column: int = Field(description="long layout: column naming the metric, or -1")
    metric: MetricName = Field(description="The metric the values represent when there is no metric column")
    unit: Literal["pct", "decimal", "bps", "currency", "ratio", "other"] = Field(description="How the numbers are written: 2.14 as pct, 0.0214 as decimal, 214 as bps")
    basis: Basis
    doc_type: DocType
    title: str
    summary: str
    key_points: list[str]
    manager: str
    as_of_date: str
    currency: str
    warnings: list[str]
