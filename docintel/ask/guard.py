"""Read-only SQL for the Ask tool. Allowlist first, then the database's own locks.

SQLite: a read-only URI connection plus an authorizer that permits only SELECT, functions and
reads of allowlisted tables (PRAGMA query_only alone still allows ATTACH and PRAGMA).
Postgres: a read-only transaction with a statement timeout.
"""
from __future__ import annotations

import re
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..db import DB_URL, IS_SQLITE, engine

ALLOWED_RELATIONS = {"v_observations", "v_documents", "v_facts", "funds"}
# tables the views read; the authorizer needs them, the SQL-level check does not allow them directly
UNDERLYING = {"observations", "documents", "funds", "facts"}
DENIED_COLUMNS = {"raw_text", "extraction_json", "refresh_token_enc"}
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace|truncate|grant|revoke|"
    r"copy|merge|call|execute|exec|load_extension|into|set|reindex|analyze|begin|commit|rollback|savepoint)\b", re.I)
IDENT = re.compile(r"\b(from|join)\s+([A-Za-z_][\w.]*)", re.I)
MAX_ROWS = 200
TIMEOUT_S = 5.0


class SQLRejected(ValueError):
    pass


def check(sql: str) -> str:
    s = re.sub(r"--[^\n]*", " ", sql or "")
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S).strip().rstrip(";").strip()
    if not s:
        raise SQLRejected("empty query")
    if ";" in s:
        raise SQLRejected("one statement only")
    if not re.match(r"^(select|with)\b", s, re.I):
        raise SQLRejected("only SELECT (or WITH ... SELECT) is allowed")
    if FORBIDDEN.search(s):
        raise SQLRejected("statement contains a forbidden keyword")
    cte_names = {m.lower() for m in re.findall(r"\b(\w+)\s+as\s*\(", s, re.I)}
    for _, ident in IDENT.findall(s):
        name = ident.split(".")[-1].lower()
        if name in cte_names or name == "(":
            continue
        if name not in ALLOWED_RELATIONS:
            raise SQLRejected(f"relation '{ident}' is not queryable; use {sorted(ALLOWED_RELATIONS)}")
    if not re.search(r"\blimit\b", s, re.I):
        s += f" LIMIT {MAX_ROWS}"
    return s


def _cell(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "…"
    return v


def _run_sqlite(sql: str) -> tuple[list[str], list[list[Any]]]:
    path = DB_URL.replace("sqlite:///", "", 1)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=TIMEOUT_S)
    try:
        def authorizer(action, arg1, arg2, _db, _trigger):
            if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                table = (arg1 or "").lower()
                if arg2 and arg2.lower() in DENIED_COLUMNS:
                    return sqlite3.SQLITE_DENY
                if table in ALLOWED_RELATIONS or table in UNDERLYING or table == "":
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY
        conn.set_authorizer(authorizer)
        deadline = time.monotonic() + TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description or []]
        rows = [[_cell(v) for v in r] for r in cur.fetchmany(MAX_ROWS)]
        return cols, rows
    finally:
        conn.close()


def _run_postgres(sql: str) -> tuple[list[str], list[list[Any]]]:
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {int(TIMEOUT_S * 1000)}"))
        res = conn.execute(text(sql))
        cols = list(res.keys())
        rows = [[_cell(v) for v in r] for r in res.fetchmany(MAX_ROWS)]
        conn.rollback()
        return cols, rows


def run(sql: str) -> tuple[list[str], list[list[Any]]]:
    safe = check(sql)
    return _run_sqlite(safe) if IS_SQLITE else _run_postgres(safe)


def dialect() -> str:
    return "SQLite" if IS_SQLITE else "PostgreSQL"
