#!/usr/bin/env python
"""Score what is in the database against corpus/answer_key.json.

Recall: every known monthly net return and key statistic should appear at least once.
Precision: every extracted monthly return should equal a known value for that fund and month.
Also reports the share of evidence fragments found verbatim in the document text.

  python scripts/eval_extraction.py corpus/answer_key.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from docintel.db import SessionLocal  # noqa: E402
from docintel.normalize import norm_fund_name  # noqa: E402

STATS = {"aum_usd": ("aum", 0.01, True), "mgmt_fee_pct": ("mgmt_fee", 0.005, False), "perf_fee_pct": ("perf_fee", 0.005, False),
         "sharpe": ("sharpe", 0.005, False), "volatility_pct": ("volatility", 0.05, False), "max_drawdown_pct": ("max_drawdown", 0.05, False)}


def cls_key(s: str) -> str:
    s = (s or "").lower().replace("class", "").replace("shares", "").strip()
    return s


def main() -> int:
    key = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "corpus/answer_key.json").read_text())
    with SessionLocal() as s:
        rows = [dict(r._mapping) for r in s.execute(text("SELECT * FROM v_observations"))]
        docs = [dict(r._mapping) for r in s.execute(text("SELECT document_id, name, status FROM v_documents"))]
        ev = {r[0]: (r[1], r[2]) for r in s.execute(text(
            "SELECT d.id, SUM(CASE WHEN o.evidence_verified THEN 1 ELSE 0 END), COUNT(*) FROM observations o JOIN documents d ON d.id=o.document_id WHERE d.is_current=1 GROUP BY d.id"))}
    by_fund = defaultdict(list)
    for r in rows:
        by_fund[norm_fund_name(r["fund"])].append(r)

    lines = ["| Fund | Monthly returns found | Stats found | Monthly rows extracted | Rows matching truth |", "|---|---|---|---|---|"]
    tot_exp = tot_found = tot_rows = tot_ok = 0
    for fname, f in key["funds"].items():
        frows = by_fund.get(norm_fund_name(fname), [])
        expected = []  # (year, month, class, value)
        for cls, c in f["classes"].items():
            for yk in ("monthly_net_pct_2026", "monthly_net_pct_2025"):
                for ym, v in (c.get(yk) or {}).items():
                    if "printed_months" in f and ym not in f["printed_months"]:
                        continue
                    expected.append((int(ym[:4]), int(ym[5:7]), "" if cls == "(none)" else cls_key(cls), v))
        found = 0
        for y, m, c, v in expected:
            hits = [r for r in frows if r["metric"] == "return" and r["period_type"] == "month" and r["period_year"] == y and r["period_month"] == m
                    and abs(r["value"] - v) < 0.005 and (c == "" or cls_key(r["share_class"]) == c or c in cls_key(r["share_class"]))]
            found += bool(hits)
        month_rows = [r for r in frows if r["metric"] == "return" and r["period_type"] == "month" and r["unit"] == "pct"]
        ok_rows = sum(1 for r in month_rows if any(r["period_year"] == y and r["period_month"] == m and abs(r["value"] - v) < 0.005 for y, m, c, v in expected))
        st_found = st_total = 0
        for k, (metric, tol, rel) in STATS.items():
            if k not in f or ("printed_stats" in f and k not in f["printed_stats"]):
                continue
            st_total += 1
            exp = f[k]
            st_found += any(r["metric"] == metric and (abs(r["value"] - exp) / abs(exp) < tol if rel else abs(abs(r["value"]) - abs(exp)) < tol) for r in frows)
        lines.append(f"| {fname} | {found}/{len(expected)} | {st_found}/{st_total} | {len(month_rows)} | {ok_rows}/{len(month_rows)} |")
        tot_exp += len(expected); tot_found += found; tot_rows += len(month_rows); tot_ok += ok_rows
    lines.append(f"| **Total** | **{tot_found}/{tot_exp} ({100*tot_found/max(1,tot_exp):.0f}% recall)** | | {tot_rows} | **{tot_ok}/{tot_rows} ({100*tot_ok/max(1,tot_rows):.0f}% precision)** |")
    print("\n".join(lines))
    print("\n| Document | Status | Evidence verified |\n|---|---|---|")
    for d in sorted(docs, key=lambda x: x["name"]):
        v, n = ev.get(d["document_id"], (0, 0))
        print(f"| {d['name']} | {d['status']} | {v}/{n} |")
    unmatched = [r for fname in key['funds'] for r in by_fund.get(norm_fund_name(fname), []) if r['metric'] == 'return' and r['period_type'] == 'month'
                 and not any(r['period_year'] == y and r['period_month'] == m and abs(r['value'] - v) < 0.005
                             for cls, c in key['funds'][fname]['classes'].items() for yk in ('monthly_net_pct_2026', 'monthly_net_pct_2025') for ym, v in (c.get(yk) or {}).items() for y, m in [(int(ym[:4]), int(ym[5:7]))])]
    if unmatched:
        print("\nMonthly rows not matching any known value:")
        for r in unmatched:
            print(f"  {r['fund']} {r['share_class']} {r['period_label']} {r['period_year']}-{r['period_month']} = {r['value']} ({r['document_name']}) basis={r['basis']} evidence={r['evidence_text'][:60]!r}")
    unknown_funds = sorted(set(by_fund) - {norm_fund_name(n) for n in key["funds"]})
    if unknown_funds:
        print("\nFunds in DB not in the key:", unknown_funds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
