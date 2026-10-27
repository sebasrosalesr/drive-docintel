from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..db import SessionLocal


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
