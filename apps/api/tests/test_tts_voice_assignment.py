"""Multi-voice TTS theo speaker — nối `diarize` (§6.5) vào `tts` (§6.9).

Hai lớp: `workers/tts/voice_assignment.py` (thuần — chọn voice theo speaker,
không I/O) và `TTSStage._voice_assignment` (đọc `Speaker`/`TranslationUnit`
thật, ghi lại `Speaker.voice_mapping`, và tự `TTSStage.run` truyền voice đã
chọn vào `SynthesisRequest`). Test stage dùng provider giả (không gọi `say`
thật) để nhanh và không phụ thuộc máy chạy test có cài voice nào.
"""

from __future__ import annotations

from core.stage import StageContext
from db.models import Project, RenderJob, Speaker, SourceVideo, Translation, TranslationUnit
from services.tts.base import SynthesisRequest, SynthesisResult, TTSConfig, TTSProvider
from workers.tts.stage import TTSStage
from workers.tts.voice_assignment import SpeakerInfo, resolve_voice_assignment
import workers.tts.stage as tts_stage_module


# ---------------------------------------------------------------------------
# voice_assignment.py — module thuần
# ---------------------------------------------------------------------------


def test_speaker_dau_tien_theo_label_luon_nhan_default_voice():
    """Chỉ một speaker (hoặc speaker đầu tiên) phải ra ĐÚNG giọng mặc định —
    không được đổi hành vi của video đơn thoại đã chạy từ trước khi có diarize."""
    speakers = [SpeakerInfo(id="s1", label="SPEAKER_00")]
    assert resolve_voice_assignment(speakers, default_voice="Primary", alt_voices=["Alt1"]) == {
        "s1": "Primary"
    }


def test_speaker_thu_hai_lay_giong_trong_pool_theo_thu_tu_label():
    speakers = [
        SpeakerInfo(id="s2", label="SPEAKER_01"),
        SpeakerInfo(id="s1", label="SPEAKER_00"),
    ]
    result = resolve_voice_assignment(speakers, default_voice="Primary", alt_voices=["Alt1", "Alt2"])
    assert result == {"s1": "Primary", "s2": "Alt1"}, (
        "phải sắp theo label trước khi gán, không theo thứ tự truyền vào list"
    )


def test_het_pool_thi_quay_lai_default_thay_vi_loi():
    """Thiếu voice phụ cấu hình không phải lý do chặn pipeline (cùng tinh
    thần bỏ qua-không-chặn của diarize)."""
    speakers = [SpeakerInfo(id=f"s{i}", label=f"SPEAKER_0{i}") for i in range(3)]
    result = resolve_voice_assignment(speakers, default_voice="Primary", alt_voices=["Alt1"])
    assert result == {"s0": "Primary", "s1": "Alt1", "s2": "Primary"}


def test_manual_voice_luon_thang_thu_tu_tu_dong():
    speakers = [
        SpeakerInfo(id="s1", label="SPEAKER_00", manual_voice="ChoTay"),
        SpeakerInfo(id="s2", label="SPEAKER_01"),
    ]
    result = resolve_voice_assignment(speakers, default_voice="Primary", alt_voices=["Alt1"])
    assert result == {"s1": "ChoTay", "s2": "Alt1"}, (
        "speaker có manual_voice không được ghi đè bởi vị trí đầu tiên"
    )


# ---------------------------------------------------------------------------
# TTSStage — DB + I/O (provider giả, không gọi TTS thật)
# ---------------------------------------------------------------------------


class _FakeProvider(TTSProvider):
    """Ghi lại mọi `SynthesisRequest` nhận được để test kiểm tra voice truyền vào."""

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.calls: list[SynthesisRequest] = []

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        self.calls.append(request)
        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        request.out_path.write_bytes(b"fake")
        voice = request.voice or self.config.voice_for(request.locale)
        return SynthesisResult(
            path=request.out_path, duration_ms=max(200, len(request.text) * 60),
            voice=voice, provider=self.id, characters=len(request.text),
        )


def _fake_config() -> TTSConfig:
    return TTSConfig(
        id="fake", name="fake", adapter="fake",
        voices={"en-US": "Primary"},
        speaker_voices={"en-US": ["Alt1", "Alt2"]},
    )


def _setup(session, storage, *, locale="en-US", with_speakers=True):
    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale=locale)
    session.add(job)
    session.flush()

    speakers = []
    if with_speakers:
        speakers = [Speaker(source_video_id=source.id, label=label) for label in ("SPEAKER_00", "SPEAKER_01")]
        session.add_all(speakers)
        session.flush()

    units = []
    for i in range(2):
        unit = TranslationUnit(
            render_job_id=job.id, idx=i,
            speaker_id=speakers[i].id if with_speakers else None,
            source_text=f"unit {i}", start_ms=i * 1000, end_ms=i * 1000 + 900,
        )
        session.add(unit)
        session.flush()
        session.add(Translation(translation_unit_id=unit.id, locale=locale, text=f"đơn vị {i}"))
        units.append(unit)
    session.flush()

    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale=locale, storage=storage,
    )
    return ctx, speakers, units


def test_hai_speaker_nhan_hai_giong_khac_nhau(session, storage, monkeypatch):
    ctx, speakers, units = _setup(session, storage)
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    result = TTSStage().run(ctx, {})

    assert [c.voice for c in fake.calls] == ["Primary", "Alt1"]
    assert result.output_ref["speakers"] == 2
    assert result.output_ref["distinct_voices"] == 2


def test_khong_co_speaker_thi_voice_la_none_giong_hanh_vi_cu(session, storage, monkeypatch):
    """diarize bị bỏ qua (thiếu token) -> speaker_id luôn None -> không được
    truyền voice ép buộc, để adapter tự chọn giọng mặc định như trước khi có
    tính năng này (không phá pipeline hiện tại)."""
    ctx, speakers, units = _setup(session, storage, with_speakers=False)
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    TTSStage().run(ctx, {})

    assert all(c.voice is None for c in fake.calls)


def test_ghi_lai_voice_mapping_tu_dong_vao_speaker(session, storage, monkeypatch):
    ctx, speakers, units = _setup(session, storage)
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    TTSStage().run(ctx, {})

    session.refresh(speakers[0])
    session.refresh(speakers[1])
    assert speakers[0].voice_mapping == {"en-US": "Primary"}
    assert speakers[1].voice_mapping == {"en-US": "Alt1"}


def test_khong_ghi_de_voice_da_set_thu_cong(session, storage, monkeypatch):
    ctx, speakers, units = _setup(session, storage)
    speakers[1].voice_mapping = {"en-US": "GiongThuCong"}
    session.flush()
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    TTSStage().run(ctx, {})

    assert fake.calls[1].voice == "GiongThuCong", (
        "giọng người dùng set thủ công phải thắng thứ tự tự động gán"
    )
    session.refresh(speakers[1])
    assert speakers[1].voice_mapping == {"en-US": "GiongThuCong"}, "không được bị ghi đè"


def test_cache_params_doi_theo_voice_assignment(session, storage, monkeypatch):
    """§16: đổi giọng phụ trong config provider mà cache key không đổi thì
    cache trả về audio giọng cũ — `voice_assignment` phải nằm trong cache_params."""
    ctx, speakers, units = _setup(session, storage)
    fake = _FakeProvider(_fake_config())
    monkeypatch.setattr(tts_stage_module, "get_tts", lambda provider_id: fake)

    params = TTSStage().cache_params(ctx)
    assert dict(params["voice_assignment"]) == {
        speakers[0].id: "Primary", speakers[1].id: "Alt1",
    }
