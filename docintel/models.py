"""Tables. One header row per document, one long row per extracted figure."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GoogleAccount(Base):
    __tablename__ = "google_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    google_sub: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")
    scopes: Mapped[str] = mapped_column(Text, default="")
    reauth_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WatchedFolder(Base):
    __tablename__ = "watched_folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    google_account_id: Mapped[int] = mapped_column(ForeignKey("google_accounts.id"))
    folder_id: Mapped[str] = mapped_column(String(128))
    folder_name: Mapped[str] = mapped_column(String(400), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_tick_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DriveFile(Base):
    """One row per file seen in the watched folder. status drives the pipeline."""
    __tablename__ = "drive_files"
    __table_args__ = (UniqueConstraint("watched_folder_id", "file_id"), Index("ix_drive_files_status", "status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    watched_folder_id: Mapped[int] = mapped_column(ForeignKey("watched_folders.id"))
    file_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(500), default="")
    mime: Mapped[str] = mapped_column(String(200), default="")
    md5: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[str] = mapped_column(String(32), default="")
    modified_time: Mapped[str] = mapped_column(String(40), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|extracting|done|needs_review|failed|removed|skipped
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extracting_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LocalFile(Base):
    """A file in the watched folder on this machine (WATCH_DIR). Same lifecycle as DriveFile."""
    __tablename__ = "local_files"
    __table_args__ = (Index("ix_local_files_status", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rel_path: Mapped[str] = mapped_column(String(1000), unique=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    mime: Mapped[str] = mapped_column(String(200), default="")
    md5: Mapped[str] = mapped_column(String(64), default="")          # unused; keeps diff() duck-typed with DriveFile
    version: Mapped[str] = mapped_column(String(32), default="")      # file size
    modified_time: Mapped[str] = mapped_column(String(40), default="")  # mtime_ns
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extracting_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    """One processed version of a file (Drive or local). is_current flips off when superseded."""
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_sha", "sha256"), Index("ix_documents_type_date", "doc_type", "as_of_date"))
    id: Mapped[int] = mapped_column(primary_key=True)
    drive_file_id: Mapped[int | None] = mapped_column(ForeignKey("drive_files.id"), nullable=True)
    parent_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # set for email attachments
    source: Mapped[str] = mapped_column(String(20), default="local")  # drive|local|folder
    name: Mapped[str] = mapped_column(String(500), default="")
    mime: Mapped[str] = mapped_column(String(200), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    text_sha256: Mapped[str] = mapped_column(String(64), default="")
    doc_type: Mapped[str] = mapped_column(String(40), default="other")
    manager: Mapped[str] = mapped_column(String(300), default="")
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    extraction_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="done")  # done|needs_review|failed
    error: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    engine: Mapped[str] = mapped_column(String(40), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    usage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Fund(Base):
    __tablename__ = "funds"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    name_norm: Mapped[str] = mapped_column(String(300), unique=True)
    manager: Mapped[str] = mapped_column(String(300), default="")
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Observation(Base):
    """One extracted figure. metric + period columns make "best January return" one WHERE clause."""
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_obs_metric_period", "metric", "period_year", "period_month"),
        Index("ix_obs_fund", "fund_id", "metric", "period_end"),
        Index("ix_obs_doc", "document_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    metric: Mapped[str] = mapped_column(String(40))
    metric_label: Mapped[str] = mapped_column(String(200), default="")
    share_class: Mapped[str] = mapped_column(String(100), default="")
    period_type: Mapped[str] = mapped_column(String(20), default="other")
    period_label: Mapped[str] = mapped_column(String(100), default="")
    period_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="pct")
    annualized: Mapped[bool] = mapped_column(Boolean, default=False)
    basis: Mapped[str] = mapped_column(String(10), default="unknown")
    currency: Mapped[str] = mapped_column(String(10), default="")
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    evidence_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_note: Mapped[str] = mapped_column(String(60), default="")
    page: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(10), default="medium")


class Fact(Base):
    """A non-performance statement with a value: a term, a size, a rate, a date."""
    __tablename__ = "facts"
    __table_args__ = (Index("ix_facts_doc", "document_id"), Index("ix_facts_attr", "attribute"))
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    subject: Mapped[str] = mapped_column(String(300), default="")
    attribute: Mapped[str] = mapped_column(String(200), default="")
    value_text: Mapped[str] = mapped_column(String(500), default="")
    value_number: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="text")
    currency: Mapped[str] = mapped_column(String(10), default="")
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    evidence_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_note: Mapped[str] = mapped_column(String(60), default="")
    page: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(10), default="medium")


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purpose: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    finish_reason: Mapped[str] = mapped_column(String(40), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
