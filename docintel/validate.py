"""Sanity checks on an extraction. Flags, never silent fixes. Any flag → needs_review."""
from __future__ import annotations

import math
from collections import defaultdict

from .schema import PERFORMANCE_TYPES, Extraction

RANGES = {
    "return": (-100.0, 500.0),
    "benchmark_return": (-100.0, 500.0),
    "expense_ratio": (0.0, 15.0),
    "mgmt_fee": (0.0, 10.0),
    "perf_fee": (0.0, 60.0),
    "sharpe": (-5.0, 10.0),
    "volatility": (0.0, 200.0),
    "max_drawdown": (-100.0, 0.0),
    "aum": (0.0, 1e13),
    "nav": (0.0, 1e13),
}


def validate(ex: Extraction, obs_rows: list[dict]) -> dict:
    flags: list[dict] = []

    performance = ex.doc_type in PERFORMANCE_TYPES
    if performance and not ex.manager.strip():
        flags.append({"code": "missing_manager", "msg": "No manager/firm identified"})
    if performance and not ex.as_of_date.strip():
        flags.append({"code": "missing_as_of", "msg": "No as-of date identified"})
    if performance and not ex.metrics:
        flags.append({"code": "no_metrics", "msg": "Performance document but no figures extracted"})
    if not ex.summary.strip():
        flags.append({"code": "no_summary", "msg": "The document could not be summarised"})

    for m in ex.metrics:
        lo, hi = RANGES.get(m.metric, (-math.inf, math.inf))
        if m.unit == "pct" and m.metric in ("max_drawdown",) and m.value > 0:
            # drawdowns printed as positive magnitudes are common; flag, don't flip
            flags.append({"code": "drawdown_sign", "msg": f"{m.fund_name} {m.period.label}: drawdown {m.value} is positive"})
        elif not (lo <= m.value <= hi):
            flags.append({"code": "out_of_range", "msg": f"{m.fund_name} {m.metric} {m.period.label} = {m.value}"})
        if m.unit == "pct" and m.metric in ("return", "benchmark_return") and abs(m.value) < 1 and m.value != 0 and ("%" not in m.evidence_text and "." in m.evidence_text) and not m.evidence_text.startswith("row "):
            # looks like a decimal fraction (0.0125) rather than percent points
            if abs(m.value) < 0.05:
                flags.append({"code": "maybe_fraction", "msg": f"{m.fund_name} {m.period.label}: {m.value} may be a fraction, not percent"})

    # monthly returns should compound to a stated calendar-year return
    months: dict[tuple, dict[int, float]] = defaultdict(dict)
    years: dict[tuple, float] = {}
    for r in obs_rows:
        if r["metric"] != "return" or r["unit"] != "pct":
            continue
        key = (r["fund_id"], r["share_class"], r["basis"], r["period_year"])
        if r["period_type"] == "month" and r["period_month"]:
            months[key][r["period_month"]] = r["value"]
        elif r["period_type"] == "year":
            years[key] = r["value"]
    for key, by_month in months.items():
        if len(by_month) == 12 and key in years:
            comp = 1.0
            for v in by_month.values():
                comp *= 1 + v / 100
            comp = (comp - 1) * 100
            if abs(comp - years[key]) > 0.5:
                flags.append({"code": "compounding_mismatch", "msg": f"12 months compound to {comp:.2f}% but year shows {years[key]:.2f}% ({key[1] or 'base'} {key[2]})"})

    checkable = [r for r in obs_rows if r.get("evidence_note") not in ("scanned", "no-text", "image-page")]
    unverified = sum(1 for r in checkable if not r.get("evidence_verified"))
    if len(checkable) >= 4 and unverified / len(checkable) > 0.3:
        flags.append({"code": "evidence_unverified", "msg": f"{unverified}/{len(checkable)} evidence fragments not found in the document text"})
    for w in ex.warnings:
        flags.append({"code": "model_warning", "msg": w})

    status = "needs_review" if [f for f in flags if f["code"] not in ("model_warning", "pii_redacted")] else "done"
    return {"status": status, "flags": flags, "n_metrics": len(ex.metrics), "n_rows": len(obs_rows), "n_facts": len(ex.facts)}
