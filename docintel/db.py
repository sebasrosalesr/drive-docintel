"""Engine, sessions and the two read views the Ask tool is allowed to query.

SQLite by default (./data/docintel.db, WAL). Postgres when DATABASE_URL is set.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _url() -> str:
    u = settings.database_url
    if not u:
        return f"sqlite:///{settings.data_dir / 'docintel.db'}"
    for prefix in ("postgres://", "postgresql://"):
        if u.startswith(prefix):
            return "postgresql+psycopg://" + u[len(prefix):]
    return u


DB_URL = _url()
IS_SQLITE = DB_URL.startswith("sqlite")

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=not IS_SQLITE,
)

if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)

# Views: the only surface the Ask tool can read. raw_text is deliberately absent.
V_OBSERVATIONS = """
SELECT o.id AS observation_id, o.document_id, d.name AS document_name, d.doc_type, d.as_of_date,
       f.id AS fund_id, f.name AS fund, f.manager, o.share_class, o.metric, o.metric_label,
       o.period_type, o.period_label, o.period_year, o.period_month, o.period_start, o.period_end,
       o.value, o.unit, o.annualized, o.basis, o.currency, o.confidence, o.evidence_verified, o.page
FROM observations o
JOIN funds f ON f.id = o.fund_id
JOIN documents d ON d.id = o.document_id
WHERE d.is_current = {TRUE}
"""
V_DOCUMENTS = """
SELECT d.id AS document_id, d.name, d.source, d.doc_type, d.title, d.summary, d.manager, d.as_of_date, d.currency,
       d.status, d.page_count, d.is_scanned, d.model, d.cost_usd, d.created_at
FROM documents d
WHERE d.is_current = {TRUE}
"""
V_FACTS = """
SELECT f.id AS fact_id, f.document_id, d.name AS document_name, d.doc_type, d.manager, d.title AS document_title,
       f.subject, f.attribute, f.value_text, f.value_number, f.unit, f.currency, f.as_of, f.confidence, f.evidence_verified, f.page
FROM facts f
JOIN documents d ON d.id = f.document_id
WHERE d.is_current = {TRUE}
"""
VIEWS = {"v_observations": V_OBSERVATIONS, "v_documents": V_DOCUMENTS, "v_facts": V_FACTS}

# Columns added after the first release; create_all does not alter existing tables.
NEW_COLUMNS = {
    "documents": [("ocr_pages", "INTEGER DEFAULT 0"), ("title", "VARCHAR(300) DEFAULT ''"), ("summary", "TEXT DEFAULT ''"), ("key_points", "JSON"), ("parent_document_id", "INTEGER")],
}


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    true_literal = "1" if IS_SQLITE else "TRUE"
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))} if IS_SQLITE else \
                {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table})}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        for name, body in VIEWS.items():
            sql = body.replace("{TRUE}", true_literal)
            if IS_SQLITE:
                conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
                conn.execute(text(f"CREATE VIEW {name} AS {sql}"))
            else:
                conn.execute(text(f"CREATE OR REPLACE VIEW {name} AS {sql}"))
