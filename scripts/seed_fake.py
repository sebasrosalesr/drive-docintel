#!/usr/bin/env python
"""Dev only: run the corpus through the pipeline with a FAKE model (answers from the answer key),
so the UI and Ask tool can be developed without an API key. Never used by the app itself.

  python scripts/seed_fake.py corpus
"""
from __future__ import annotations

import json
import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_corpus as mc  # noqa: E402
from docintel.db import SessionLocal, init_db  # noqa: E402
from docintel.pipeline import process_bytes  # noqa: E402

MON = {i: m for i, m in mc.MON.items()}


def metric(fund, cls, name, label, ptype, plabel, start, end, value, unit="pct", basis="net", ev="", page=1, conf="high", ann=False):
    return {"fund_name": fund, "share_class": cls, "metric": name, "metric_label": label, "period": {"type": ptype, "label": plabel, "start": start, "end": end},
            "value": value, "unit": unit, "annualized": ann, "basis": basis, "currency": "USD", "evidence_text": ev or f"{plabel} {value:.2f}", "page": page, "confidence": conf}


def months(fund, cls, vals, year=2026, basis="net"):
    out = []
    for i, v in enumerate(vals):
        m = i + 1
        import calendar
        out.append(metric(fund, cls, "return", "Net return", "month", f"{MON[m]} {year}", f"{year}-{m:02d}-01", f"{year}-{m:02d}-{calendar.monthrange(year, m)[1]}", v, basis=basis, ev=f"{MON[m]} {v:.2f}"))
    return out


def stats(fund, f, as_of):
    return [metric(fund, "", "aum", "Fund AUM", "point", "as of", as_of, as_of, f["aum"], unit="currency", basis="unknown", ev=mc.money(f["aum"])),
            metric(fund, "", "mgmt_fee", "Management fee", "point", "p.a.", "", as_of, f["mgmt_fee"], basis="unknown", ev=f"{f['mgmt_fee']:.2f}%"),
            metric(fund, "", "perf_fee", "Performance fee", "point", "", "", as_of, f["perf_fee"], basis="unknown", ev=f"{f['perf_fee']:.0f}%"),
            metric(fund, "", "sharpe", "Sharpe ratio", "since_inception", "since inception", "", as_of, f["sharpe"], unit="ratio", basis="unknown", ann=True, ev=f"{f['sharpe']:.2f}"),
            metric(fund, "", "volatility", "Annualised volatility", "since_inception", "since inception", "", as_of, f["vol"], basis="unknown", ann=True, ev=f"{f['vol']:.1f}%"),
            metric(fund, "", "max_drawdown", "Maximum drawdown", "since_inception", "since inception", "", as_of, f["mdd"], basis="unknown", ev=f"{f['mdd']:.1f}%")]


def fake_extraction(name: str) -> dict:
    F = mc.FUNDS
    as_of = "2026-09-30"
    if name.startswith("Northwind"):
        through = 8 if "Aug" in name else 9
        as_of = f"2026-{through:02d}-{30 if through == 9 else 31}"
        fund = "Northwind Global Macro Fund LP"; f = F[fund]
        mets = []
        for cls, vals in f["classes"].items():
            mets += months(fund, cls, vals[:through])
            mets.append(metric(fund, cls, "return", "YTD", "ytd", "YTD", "2026-01-01", as_of, mc.compound(vals[:through]), ev=f"YTD {mc.compound(vals[:through]):.2f}"))
        mets += stats(fund, f, as_of)
        return {"doc_type": "factsheet", "manager": f["manager"], "manager_evidence": "NORTHWIND CAPITAL MANAGEMENT", "as_of_date": as_of, "as_of_evidence": "Data as of", "currency": "USD",
                "funds": [{"name": fund, "share_class": "Class A", "strategy": "Global Macro", "evidence_text": fund}, {"name": fund, "share_class": "Class I", "strategy": "Global Macro", "evidence_text": fund}],
                "metrics": mets, "warnings": []}
    if name.startswith("northwind_monthly"):
        fund = "Northwind Global Macro Fund LP"; f = F[fund]
        mets = months(fund, "Class A", f["r2025"], year=2025) + months(fund, "Class A", f["classes"]["Class A"]) + months(fund, "Class I", f["classes"]["Class I"])
        return {"doc_type": "performance_report", "manager": "Northwind Capital Management", "manager_evidence": "Northwind", "as_of_date": as_of, "as_of_evidence": "2026-09-30", "currency": "USD",
                "funds": [{"name": fund, "share_class": "", "strategy": "", "evidence_text": fund}], "metrics": mets, "warnings": ["manager inferred from fund name; CSV has no header block"]}
    if name.startswith("HarborPoint"):
        fund = "Harbor Point Credit Opportunities Fund"; f = F[fund]; v = f["classes"][""]
        if "Letter" in name:
            mets = months(fund, "", v) + stats(fund, f, as_of) + [metric(fund, "", "return", "YTD net", "ytd", "year-to-date", "2026-01-01", as_of, mc.compound(v))]
            return {"doc_type": "factsheet", "manager": f["manager"], "manager_evidence": "Harbor Point Partners", "as_of_date": as_of, "as_of_evidence": "30 September 2026", "currency": "USD",
                    "funds": [{"name": fund, "share_class": "", "strategy": "Credit Long/Short", "evidence_text": fund}], "metrics": mets, "warnings": []}
        if "Q3" in name:
            mets = months(fund, "", v)[6:9] + [metric(fund, "", "benchmark_return", f["benchmark"], "month", f"{MON[i+1]} 2026", f"2026-{i+1:02d}-01", f"2026-{i+1:02d}-30", f["bench"][i], basis="unknown") for i in range(6, 9)]
            mets.append(metric(fund, "", "return", "Q3 2026 net", "quarter", "Q3 2026", "2026-07-01", as_of, mc.compound(v[6:9])))
            return {"doc_type": "performance_report", "manager": f["manager"], "manager_evidence": "Harbor Point Partners", "as_of_date": as_of, "as_of_evidence": "30 Sep 2026", "currency": "USD",
                    "funds": [{"name": fund, "share_class": "", "strategy": "", "evidence_text": fund}], "metrics": mets, "warnings": []}
        mets = [metric(fund, "", "return", "Net return (estimate)", "month", "Sep 2026 (estimate)", "2026-09-01", as_of, v[8], conf="medium"),
                metric(fund, "", "return", "Net return", "month", "Aug 2026", "2026-08-01", "2026-08-31", v[7]),
                metric(fund, "", "return", "Net return", "ytd", "YTD 2026", "2026-01-01", as_of, mc.compound(v)),
                metric(fund, "", "aum", "Estimated AUM", "point", "month end", as_of, as_of, f["aum"], unit="currency", basis="unknown", conf="medium")]
        return {"doc_type": "email_update", "manager": f["manager"], "manager_evidence": "Harbor Point Partners", "as_of_date": as_of, "as_of_evidence": "September 2026", "currency": "USD",
                "funds": [{"name": fund, "share_class": "", "strategy": "", "evidence_text": fund}], "metrics": mets, "warnings": ["September figure is a flash estimate"]}
    if name.startswith("SableRidge") or name.startswith("sable_ridge"):
        fund = "Sable Ridge Equity Long/Short"; f = F[fund]; v = f["classes"][""]
        mets = months(fund, "", v) + [metric(fund, "", "return", "YTD", "ytd", "YTD", "2026-01-01", as_of, mc.compound(v))]
        if name.startswith("SableRidge"):
            mets += stats(fund, f, as_of)
        return {"doc_type": "factsheet" if name.startswith("SableRidge") else "performance_report", "manager": f["manager"], "manager_evidence": "Sable Ridge Asset Management",
                "as_of_date": as_of, "as_of_evidence": "30/09/2026", "currency": "USD", "funds": [{"name": fund, "share_class": "", "strategy": "Equity Long/Short", "evidence_text": fund}], "metrics": mets, "warnings": []}
    if name.startswith("Meridian"):
        fund = "Meridian Systematic Trend Fund"; f = F[fund]; v = f["classes"][""]
        mets = months(fund, "", v) + [metric(fund, "", "return", "YTD", "ytd", "YTD 2026", "2026-01-01", as_of, mc.compound(v))] + stats(fund, f, as_of)
        for m in mets:
            m["confidence"] = "medium"
        return {"doc_type": "factsheet", "manager": f["manager"], "manager_evidence": "MERIDIAN QUANT", "as_of_date": as_of, "as_of_evidence": "30 September 2026", "currency": "USD",
                "funds": [{"name": fund, "share_class": "", "strategy": "Managed Futures / Trend", "evidence_text": fund}], "metrics": mets, "warnings": ["scanned page; read visually"]}
    if name.startswith("CobaltRow"):
        fund = "Cobalt Row Multi-Strategy Fund"; f = F[fund]; v = f["classes"][""]
        mets = [metric(fund, "", "return", "Period performance (net)", "quarter", "the quarter", "2026-07-01", as_of, mc.compound(v[6:9])),
                metric(fund, "", "return", "Year to date", "ytd", "year to date", "2026-01-01", as_of, mc.compound(v)),
                metric(fund, "", "return", "September", "month", "September", "2026-09-01", as_of, v[8]),
                metric(fund, "", "nav", "NAV per unit", "point", "30 Sep 2026", as_of, as_of, 1312.4471, unit="currency", basis="unknown"),
                metric(fund, "", "aum", "Fund net assets", "point", "period end", as_of, as_of, f["aum"], unit="currency", basis="unknown"),
                metric(fund, "", "mgmt_fee", "management", "point", "", "", as_of, f["mgmt_fee"], basis="unknown"),
                metric(fund, "", "perf_fee", "incentive", "point", "", "", as_of, f["perf_fee"], basis="unknown")]
        return {"doc_type": "statement", "manager": f["manager"], "manager_evidence": "COBALT ROW ADVISORS LLC", "as_of_date": as_of, "as_of_evidence": "30 Sep 2026", "currency": "USD",
                "funds": [{"name": fund, "share_class": "", "strategy": "Multi-Strategy", "evidence_text": fund}], "metrics": mets, "warnings": []}
    return {"doc_type": "other", "manager": "", "manager_evidence": "", "as_of_date": "", "as_of_evidence": "", "currency": "", "funds": [], "metrics": [], "warnings": ["not a financial document: holiday schedule"]}


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    init_db()
    mimetypes.add_type("message/rfc822", ".eml")
    for p in sorted(folder.iterdir()):
        if p.suffix in (".json",) or p.name.startswith("."):
            continue
        ex = fake_extraction(p.name)

        def transport(body, _ex=ex):
            return {"model": "fake/answer-key", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(_ex)}}],
                    "usage": {"prompt_tokens": 4000, "completion_tokens": 900, "cost": 0.0}}

        with SessionLocal() as s:
            doc = process_bytes(s, name=p.name, mime=mimetypes.guess_type(p.name)[0] or "", data=p.read_bytes(), source="local", force=True, transport=transport)
            v = doc.validation_json or {}
            print(f"  {p.name:<46} {doc.status:<12} rows={v.get('n_rows', 0):>3} flags={[f['code'] for f in v.get('flags', []) if f['code'] != 'model_warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
