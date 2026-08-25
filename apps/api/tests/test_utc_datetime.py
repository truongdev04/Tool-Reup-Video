"""`db.base.UTCDateTime` — bug thật bắt được khi test luồng OAuth qua HTTP
thật (Phase 5): SQLite lưu `DateTime(timezone=True)` được nhưng ĐỌC LẠI trả
về datetime NAIVE (mất tzinfo). So sánh với `datetime.now(UTC)` (tz-aware) ở
`PlatformAccount.is_usable_at`/`VoiceConsent.is_valid_at` thì
`TypeError: can't compare offset-naive and offset-aware datetimes` — nhưng
CHỈ lộ ra khi object được nạp lại từ một SESSION MỚI (đúng luồng thật: request
A ghi, request B đọc). Test khác trong repo tạo object rồi dùng ngay trong
CÙNG session nên không bao giờ thấy bug này — file này cố tình dựng lại đúng
kịch bản hai session để khoá lại fix, không lặp lại sai lầm cũ.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import PlatformAccount, VoiceConsent


def _two_sessions():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return maker()


def test_platform_account_doc_lai_tu_session_moi_van_co_tzinfo():
    session_a = _two_sessions()
    engine_maker = session_a.get_bind()

    account = PlatformAccount(
        platform="mock", label="x", access_token_encrypted="enc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session_a.add(account)
    session_a.commit()
    account_id = account.id
    session_a.close()

    session_b = sessionmaker(bind=engine_maker, expire_on_commit=False, future=True)()
    fresh = session_b.get(PlatformAccount, account_id)

    assert fresh.expires_at.tzinfo is not None, "mất tzinfo sau round-trip qua SQLite"
    # Đây chính là lời gọi từng ném TypeError trước khi có UTCDateTime.
    assert fresh.is_usable_at(datetime.now(UTC)) is True


def test_voice_consent_doc_lai_tu_session_moi_van_so_sanh_duoc():
    session_a = _two_sessions()
    engine_maker = session_a.get_bind()

    consent = VoiceConsent(
        subject_name="A", scope="test",
        granted_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session_a.add(consent)
    session_a.commit()
    consent_id = consent.id
    session_a.close()

    session_b = sessionmaker(bind=engine_maker, expire_on_commit=False, future=True)()
    fresh = session_b.get(VoiceConsent, consent_id)

    assert fresh.is_valid_at(datetime.now(UTC)) is True
