#!/usr/bin/env python
"""Turn a document's current reading into a gold file a human can correct, for regression evals on real documents.

  python scripts/gold_export.py 10 12 15        # writes gold/<sha256>.json per document
Edit the files (fix values, delete wrong rows, add missing ones), commit them, then run scripts/eval_gold.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from docintel.db import SessionLocal  # noqa: E402
from docintel.models import Document, Fact, Fund, Observation  # noqa: E402


def main() -> int:
    ids = [int(x) for x in sys.argv[1:]]
    if not ids:
        print(__doc__)
        return 1
    out_dir = Path("gold")
    out_dir.mkdir(exist_ok=True)
    with SessionLocal() as s:
        funds = {f.id: f.name for f in s.scalars(select(Fund))}
        for did in ids:
            d = s.get(Document, did)
            if d is None:
                print(f"no document {did}")
                continue
            figs = [{"fund": funds.get(o.fund_id, ""), "share_class": o.share_class, "metric": o.metric, "period_type": o.period_type, "period_label": o.period_label,
                     "period_year": o.period_year, "period_month": o.period_month, "value": o.value, "unit": o.unit, "basis": o.basis}
                    for o in s.scalars(select(Observation).where(Observation.document_id == d.id).order_by(Observation.id))]
            facts = [{"subject": f.subject, "attribute": f.attribute, "value_text": f.value_text, "value_number": f.value_number, "unit": f.unit}
                     for f in s.scalars(select(Fact).where(Fact.document_id == d.id).order_by(Fact.id))]
            gold = {"sha256": d.sha256, "name": d.name, "title": d.title, "doc_type": d.doc_type, "manager": d.manager, "as_of_date": d.as_of_date.isoformat() if d.as_of_date else None,
                    "figures": figs, "facts": facts, "note": "Edit to the truth. Figures match on fund+metric+period+value; facts on attribute+value_text."}
            path = out_dir / f"{d.sha256}.json"
            path.write_text(json.dumps(gold, indent=2))
            print(f"wrote {path} ({len(figs)} figures, {len(facts)} facts) for {d.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
