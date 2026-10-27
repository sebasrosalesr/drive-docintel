#!/usr/bin/env python
"""Ingest a local folder through the same pipeline the Drive sync uses. No Google needed.

  python scripts/run_local.py corpus [--force] [--engine native|mistral-ocr] [--effort low|medium|high] [--workers 3]
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docintel.db import SessionLocal, init_db  # noqa: E402
from docintel.pipeline import Unsupported, process_bytes  # noqa: E402
from docintel.render import kind_for  # noqa: E402

mimetypes.add_type("message/rfc822", ".eml")


def one(path: Path, args) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with SessionLocal() as session:
        t0 = time.perf_counter()
        try:
            doc = process_bytes(session, name=path.name, mime=mime, data=path.read_bytes(), source="local",
                                force=args.force, engine=args.engine, effort=args.effort, model=args.model)
        except Unsupported as exc:
            return {"name": path.name, "status": "skipped", "note": str(exc)}
        flags = [f["code"] for f in (doc.validation_json or {}).get("flags", [])]
        return {"name": path.name, "status": doc.status, "type": doc.doc_type, "manager": doc.manager,
                "as_of": str(doc.as_of_date or ""), "rows": (doc.validation_json or {}).get("n_rows", 0),
                "cost": doc.cost_usd, "ms": int((time.perf_counter() - t0) * 1000),
                "note": doc.error[:80] if doc.error else ", ".join(flags)[:80]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--engine", default=None)
    ap.add_argument("--effort", default=None)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--model", default=None, help="override MODEL for this run")
    args = ap.parse_args()
    init_db()
    files = sorted(p for p in Path(args.folder).iterdir() if p.is_file() and not p.name.startswith(".") and kind_for(p.name, "") != "unsupported")
    print(f"{len(files)} files")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one, p, args): p for p in files}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"  {r['name'][:44]:<44} {r['status']:<12} {r.get('type',''):<18} {r.get('rows',''):>4} rows  ${r.get('cost',0):.4f}  {r.get('ms',0):>6} ms  {r.get('note','')}")
    total = sum(r.get("cost", 0) for r in results)
    print(f"total cost ${total:.4f}; statuses: " + ", ".join(f"{s}={sum(1 for r in results if r['status']==s)}" for s in sorted({r['status'] for r in results})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
