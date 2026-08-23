"""Engine, session và Base cho SQLAlchemy.

SQLite cho Phase 0–2, PostgreSQL từ Phase 3 (docs §13). Model viết theo kiểu
portable giữa hai loại DB: id là chuỗi UUID, dict lưu bằng JSON.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from core.config import get_settings


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class PKMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


_settings = get_settings()
engine = create_engine(_settings.database_url, future=True)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    """Bật foreign key cho SQLite — mặc định SQLite TẮT, khiến ràng buộc quan hệ
    im lặng không có tác dụng và lineage (§10.4) hỏng mà không báo lỗi."""
    if _settings.database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator:
    """Session có commit/rollback tự động."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    from db import models  # noqa: F401  — đăng ký model vào metadata

    Base.metadata.create_all(engine)
