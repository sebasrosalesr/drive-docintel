#!/usr/bin/env python
"""Re-run evidence verification on stored figures and facts using the stored document text. No model calls.
Useful after improving the matcher.  python scripts/reverify.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from docintel.db import SessionLocal  # noqa: E402
from docintel.models import Document, Fact, Observation  # noqa: E402
from docintel.normalize import page_texts, verify_evidence  # noqa: E402
from docintel.validate import validate  # noqa: E402
from docintel.schema import Extraction  # noqa: E402


def main() -> int:
    changed = total = 0
    with SessionLocal() as s:
        for d in s.scalars(select(Document).where(Document.is_current.is_(True), Document.status != "failed")):
            pages = page_texts(d.raw_text or "")
            scanned = d.is_scanned
            rows = []
            for o in s.scalars(select(Observation).where(Observation.document_id == d.id)):
                ok, note = verify_evidence(o.evidence_text, d.raw_text or "", scanned=scanned, page=o.page, pages=pages)
                total += 1
                if ok != o.evidence_verified:
                    changed += 1
                o.evidence_verified, o.evidence_note = ok, note
                rows.append({"fund_id": o.fund_id, "share_class": o.share_class, "basis": o.basis, "metric": o.metric, "unit": o.unit, "value": o.value,
                             "period_type": o.period_type, "period_year": o.period_year, "period_month": o.period_month, "evidence_verified": ok, "evidence_note": note})
            for f in s.scalars(select(Fact).where(Fact.document_id == d.id)):
                ok, note = verify_evidence(f.evidence_text, d.raw_text or "", scanned=scanned, page=f.page, pages=pages)
                total += 1
                if ok != f.evidence_verified:
                    changed += 1
                f.evidence_verified, f.evidence_note = ok, note
            if d.extraction_json:
                try:
                    v = validate(Extraction.model_validate(d.extraction_json), rows)
                    d.validation_json, d.status = v, v["status"]
                except Exception:  # noqa: BLE001  older extraction shapes
                    pass
        s.commit()
    print(f"re-verified {total} rows, {changed} changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
