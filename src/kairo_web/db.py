"""Database engine + session factory."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from kairo_web.config import get_settings


def _build_engine() -> Engine:
    settings = get_settings()
    connect_args: dict[str, object] = {}
    if settings.KAIRO_DATABASE_URL.startswith("sqlite"):
        # Required for SQLite when used across threads (uvicorn workers).
        connect_args["check_same_thread"] = False
    return create_engine(
        settings.KAIRO_DATABASE_URL,
        echo=False,
        connect_args=connect_args,
    )


engine: Engine = _build_engine()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a SQLModel session per request."""
    with Session(engine) as session:
        yield session
