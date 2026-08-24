"""Voice consent chặn TTS cho giọng nhân bản thiếu chứng từ (§18.2).

Hai lớp: `services/voice_consent.py` (tra cứu thuần — chỉ đọc DB, không
synthesize) và `TTSStage._enforce_voice_consent` (nối vào `run()` thật, chặn
TRƯỚC khi tốn công đọc thoại). Provider giả để không gọi TTS thật, cùng mẫu
với `test_tts_voice_assignment.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.stage import NonRetryableError, StageContext
from db.models import (
    Project,
    RenderJob,
    SourceVideo,
    Translation,
    TranslationUnit,
    Voice,
    VoiceConsent,
)
from services.tts.base import SynthesisRequest, SynthesisResult, TTSConfig, TTSProvider
from services.voice_consent import ensure_voice_consent
from workers.tts.stage import TTSStage
import workers.tts.stage as tts_stage_module


def _consent(session, *, valid: bool = True, revoked: bool = False) -> VoiceConsent:
    now = datetime.now(UTC)
    consent = VoiceConsent(
        subject_name="Người mẫu giọng", scope="quảng cáo nội bộ",
        granted_at=now - timedelta(days=1),
        expires_at=None if valid else now - timedelta(days=1),
        is_revoked=revoked,
    )
    session.add(consent)
    session.flush()
    return consent


# ---------------------------------------------------------------------------
# services/voice_consent.py — tra cứu thuần
# ---------------------------------------------------------------------------


def test_giong_chua_dang_ky_khong_bi_chan(session):
    """Chưa ai khai voice_id này là giọng nhân bản -> không tự suy diễn, không chặn."""
    ensure_voice_consent(session, provider="elevenlabs", voice_id="unregistered-id")


def test_giong_dang_ky_nhung_khong_phai_clone_khong_bi_chan(session):
    session.add(Voice(
        name="X", provider="elevenlabs", provider_voice_id="v1",
        locale="en-US", is_cloned=False,
    ))
    session.flush()
    ensure_voice_consent(session, provider="elevenlabs", voice_id="v1")


def test_giong_clone_thieu_consent_bi_chan(session):
    session.add(Voice(
        name="X", provider="elevenlabs", provider_voice_id="v1",
        locale="en-US", is_cloned=True,
    ))
    session.flush()
    with pytest.raises(NonRetryableError, match="voice_consent"):
        ensure_voice_consent(session, provider="elevenlabs", voice_id="v1")


def test_giong_clone_consent_het_han_bi_chan(session):
    consent = _consent(session, valid=False)
    session.add(Voice(
        name="X", provider="elevenlabs", provider_voice_id="v1",
        locale="en-US", is_cloned=True, consent_id=consent.id,
    ))
    session.flush()
    with pytest.raises(NonRetryableError):
        ensure_voice_consent(session, provider="elevenlabs", voice_id="v1")


def test_giong_clone_consent_bi_thu_hoi_bi_chan(session):
    consent = _consent(session, valid=True, revoked=True)
    session.add(Voice(
        name="X", provider="elevenlabs", provider_voice_id="v1",
        locale="en-US", is_cloned=True, consent_id=consent.id,
    ))
    session.flush()
    with pytest.raises(NonRetryableError):
        ensure_voice_consent(session, provider="elevenlabs", voice_id="v1")


def test_giong_clone_consent_hop_le_khong_bi_chan(session):
    consent = _consent(session, valid=True)
    session.add(Voice(
        name="X", provider="elevenlabs", provider_voice_id="v1",
        locale="en-US", is_cloned=True, consent_id=consent.id,
    ))
    session.flush()
    ensure_voice_consent(session, provider="elevenlabs", voice_id="v1")


def test_provider_khac_nhau_khong_lay_nham_dang_ky(session):
    """Cùng voice_id nhưng khác provider phải coi là giọng khác — voice `Fred`
    của `macos_say` không liên quan gì tới một giọng nhân bản trùng tên ở
    provider khác."""
    session.add(Voice(
        name="X", provider="elevenlabs", provider_voice_id="Fred",
        locale="en-US", is_cloned=True,
    ))
    session.flush()
    ensure_voice_consent(session, provider="macos_say", voice_id="Fred")


# ---------------------------------------------------------------------------
# TTSStage._enforce_voice_consent — nối vào stage thật
# ---------------------------------------------------------------------------


class _FakeProvider(TTSProvider):
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        request.out_path.write_bytes(b"fake")
        voice = request.voice or self.config.voice_for(request.locale)
        return SynthesisResult(
            path=request.out_path, duration_ms=300, voice=voice,
            provider=self.id, characters=len(request.text),
        )


def _fake_config() -> TTSConfig:
    return TTSConfig(id="fake", name="fake", adapter="fake", voices={"en-US": "ClonedVoice"})


def _setup(session, storage) -> StageContext:
    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="en-US")
    session.add(job)
    session.flush()
    unit = TranslationUnit(render_job_id=job.id, idx=0, source_text="hi", start_ms=0, end_ms=900)
    session.add(unit)
    session.flush()
    session.add(Translation(translation_unit_id=unit.id, locale="en-US", text="chào"))
    session.flush()
    return StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="en-US", storage=storage,
    )


def test_tts_stage_chan_khi_giong_mac_dinh_la_clone_thieu_consent(session, storage, monkeypatch):
    ctx = _setup(session, storage)
    session.add(Voice(
        name="Cloned", provider="fake", provider_voice_id="ClonedVoice",
        locale="en-US", is_cloned=True,
    ))
    session.flush()
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    with pytest.raises(NonRetryableError, match="voice_consent"):
        TTSStage().run(ctx, {})


def test_tts_stage_chay_binh_thuong_khi_giong_chua_dang_ky(session, storage, monkeypatch):
    ctx = _setup(session, storage)
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    result = TTSStage().run(ctx, {})

    assert result.output_ref["chunks"] == 1


def test_tts_stage_chay_duoc_khi_clone_co_consent_hop_le(session, storage, monkeypatch):
    ctx = _setup(session, storage)
    consent = _consent(session, valid=True)
    session.add(Voice(
        name="Cloned", provider="fake", provider_voice_id="ClonedVoice",
        locale="en-US", is_cloned=True, consent_id=consent.id,
    ))
    session.flush()
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    result = TTSStage().run(ctx, {})

    assert result.output_ref["chunks"] == 1
