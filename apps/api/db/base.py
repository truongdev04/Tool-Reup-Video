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
from sqlalchemy.types import TypeDecorator

from core.config import get_settings


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """`DateTime(timezone=True)` mà đọc lại LUÔN có tzinfo=UTC.

    Bug thật đã bắt được (Phase 5, khi test luồng OAuth qua HTTP thật — không
    lộ ra ở unit test vì object tái dùng trong CÙNG session, chưa từng round-trip
    qua driver): SQLite lưu `DateTime(timezone=True)` được, nhưng đọc lại trả
    về datetime NAIVE (mất tzinfo) — so sánh với `datetime.now(UTC)` (tz-aware)
    ở `PlatformAccount.is_usable_at`/`VoiceConsent.is_valid_at` ném
    `TypeError: can't compare offset-naive and offset-aware datetimes` ngay
    khi object được nạp lại từ một session MỚI (đúng luồng thật: request A ghi
    token, request B đọc lại để kiểm hạn — hai session khác nhau).

    PostgreSQL (§13, dự kiến từ Phase 3) không có bug này — tzinfo giữ nguyên
    qua TIMESTAMPTZ — nên `process_result_value` ở đó là no-op an toàn, không
    phải patch riêng cho từng DB.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class PKMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


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
