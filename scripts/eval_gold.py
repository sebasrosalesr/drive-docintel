#!/usr/bin/env python
"""Score the current readings against the human-corrected gold files in gold/.

  python scripts/eval_gold.py
Recall = gold rows found in the current reading; precision = current rows present in gold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from docintel.db import SessionLocal  # noqa: E402
from docintel.models import Document, Fact, Fund, Observation  # noqa: E402
from docintel.normalize import norm_fund_name  # noqa: E402


def fig_key(r: dict) -> tuple:
    return (norm_fund_name(r.get("fund", "")), (r.get("share_class") or "").lower(), r["metric"], r["period_type"], r.get("period_year"), r.get("period_month"), round(float(r["value"]), 4))


def fact_key(r: dict) -> tuple:
    return ((r.get("attribute") or "").strip().lower(), " ".join((r.get("value_text") or "").split()).lower())


def main() -> int:
    files = sorted(Path("gold").glob("*.json"))
    if not files:
        print("no gold files; run scripts/gold_export.py first")
        return 1
    lines = ["| Document | Figures recall | Figures precision | Facts recall | Facts precision | Type/manager/as-of |", "|---|---|---|---|---|---|"]
    tf = tfg = tp = tpg = 0
    with SessionLocal() as s:
        funds = {f.id: f.name for f in s.scalars(select(Fund))}
        for path in files:
            gold = json.loads(path.read_text())
            d = s.scalar(select(Document).where(Document.sha256 == gold["sha256"], Document.is_current.is_(True)))
            if d is None:
                lines.append(f"| {gold['name']} | not in library | | | | |")
                continue
            cur_f = {fig_key({"fund": funds.get(o.fund_id, ""), "share_class": o.share_class, "metric": o.metric, "period_type": o.period_type, "period_year": o.period_year, "period_month": o.period_month, "value": o.value})
                     for o in s.scalars(select(Observation).where(Observation.document_id == d.id))}
            gold_f = {fig_key(r) for r in gold["figures"]}
            cur_k = {fact_key({"attribute": f.attribute, "value_text": f.value_text}) for f in s.scalars(select(Fact).where(Fact.document_id == d.id))}
            gold_k = {fact_key(r) for r in gold["facts"]}
            fr = len(gold_f & cur_f); fp = len(cur_f & gold_f)
            kr = len(gold_k & cur_k); kp = len(cur_k & gold_k)
            meta = "✓" if (d.doc_type == gold["doc_type"] and (d.as_of_date.isoformat() if d.as_of_date else None) == gold["as_of_date"]) else f"{d.doc_type}/{d.as_of_date}"
            lines.append(f"| {gold['name'][:40]} | {fr}/{len(gold_f)} | {fp}/{len(cur_f)} | {kr}/{len(gold_k)} | {kp}/{len(cur_k)} | {meta} |")
            tf += fr; tfg += len(gold_f); tp += kr; tpg += len(gold_k)
    lines.append(f"| **Total** | **{tf}/{tfg}** | | **{tp}/{tpg}** | | |")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
