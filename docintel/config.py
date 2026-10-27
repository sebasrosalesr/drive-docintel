"""Settings from the environment. A `.env` at the repo root is loaded first."""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _s(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _i(name: str, default: int) -> int:
    try:
        return int(_s(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    model: str
    ask_model: str
    fallback_model: str
    pdf_engine: str
    reasoning_effort: str
    # Spreadsheets and CSVs are already structured: a lighter think is enough and several times faster.
    table_reasoning_effort: str
    app_secret: str
    base_url: str
    database_url: str
    sync_interval_seconds: int
    extract_concurrency: int
    google_client_id: str
    google_client_secret: str
    data_dir: Path
    watch_dir: Path | None
    pii_identity_policy: str
    pii_redact: bool
    app_password: str
    daily_cost_cap_usd: float

    @property
    def fernet_key(self) -> bytes:
        return base64.urlsafe_b64encode(hashlib.sha256(self.app_secret.encode()).digest())

    @property
    def is_local(self) -> bool:
        return self.base_url.startswith(("http://localhost", "http://127."))

    @property
    def google_ready(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def llm_ready(self) -> bool:
        return bool(self.openrouter_api_key)


def load() -> Settings:
    data_dir = Path(_s("DATA_DIR")) if _s("DATA_DIR") else ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    return Settings(
        openrouter_api_key=_s("OPENROUTER_API_KEY"),
        model=_s("MODEL", "google/gemini-4-argon"),
        ask_model=_s("ASK_MODEL") or _s("MODEL", "google/gemini-4-argon"),
        fallback_model=_s("FALLBACK_MODEL") if os.getenv("FALLBACK_MODEL") is not None else "anthropic/claude-opus-5.5",
        pdf_engine=_s("PDF_ENGINE", "native"),
        reasoning_effort=_s("REASONING_EFFORT", "medium"),
        table_reasoning_effort=_s("TABLE_REASONING_EFFORT", "low").lower(),
        app_secret=_s("APP_SECRET", "dev-secret-change-me"),
        base_url=_s("BASE_URL", "http://localhost:8080").rstrip("/"),
        database_url=_s("DATABASE_URL"),
        sync_interval_seconds=_i("SYNC_INTERVAL_SECONDS", 60),
        extract_concurrency=_i("EXTRACT_CONCURRENCY", 3),
        google_client_id=_s("GOOGLE_CLIENT_ID"),
        google_client_secret=_s("GOOGLE_CLIENT_SECRET"),
        data_dir=data_dir,
        watch_dir=Path(_s("WATCH_DIR")).expanduser() if _s("WATCH_DIR") else None,
        pii_identity_policy=_s("PII_IDENTITY_POLICY", "reject").lower(),
        pii_redact=_s("PII_REDACT", "1").lower() in ("1", "true", "yes", "on"),
        app_password=_s("APP_PASSWORD"),
        daily_cost_cap_usd=float(_s("DAILY_COST_CAP_USD", "0") or 0),
    )


settings = load()
