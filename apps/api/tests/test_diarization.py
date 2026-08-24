"""Diarize — docs §6.5.

Hai lớp tách biệt theo đúng mẫu "logic thuần tách khỏi I/O" (coding-style.md):
`workers/diarization/assign.py` (gán nhãn speaker, không I/O) và
`workers/diarization/stage.py` (đọc DB + gọi pyannote thật qua
`services/diarization_pyannote.py`). Môi trường test KHÔNG có `pyannote.audio`
cài sẵn và không có `HF_TOKEN` — đây chính là kịch bản "bỏ qua" mà stage phải
xử lý mà không sập, nên test được thẳng bằng code path thật, không cần mock.
"""

from __future__ import annotations

from core.stage import StageContext
from core.types import ArtifactKind
from db.models import Project, RenderJob, Speaker, SourceVideo, STTSegment, Transcript
from workers.diarization.assign import (
    DiarizationTurn,
    SegmentSpan,
    assign_speakers,
    total_speech_ms,
)
from workers.diarization.stage import DiarizeStage
import workers.diarization.stage as diarize_stage_module


def _turn(start, end, speaker):
    return DiarizationTurn(start_ms=start, end_ms=end, speaker=speaker)


def _span(idx, start, end):
    return SegmentSpan(idx=idx, start_ms=start, end_ms=end)


# ---------------------------------------------------------------------------
# assign.py — module thuần
# ---------------------------------------------------------------------------


def test_gan_speaker_co_overlap_lon_nhat():
    """Segment chồng lấn nhiều lượt nói phải lấy nhãn của lượt chồng NHIỀU
    NHẤT, không phải lượt đến trước hay lượt gần điểm bắt đầu segment nhất."""
    segments = [_span(0, 0, 1000)]
    turns = [_turn(0, 200, "A"), _turn(200, 1000, "B")]
    assert assign_speakers(segments, turns) == {0: "B"}


def test_segment_khong_cham_luot_noi_nao_thi_vang_mat_trong_ket_qua():
    """Segment rơi đúng vào khoảng lặng giữa hai lượt nói không được gán bừa
    một speaker — downstream coi vắng mặt = giữ nguyên `speaker_id=None`."""
    segments = [_span(0, 100, 200)]
    turns = [_turn(0, 50, "A"), _turn(250, 300, "B")]
    assert assign_speakers(segments, turns) == {}


def test_nhieu_segment_gan_dung_nguoi_noi_tuong_ung():
    segments = [_span(0, 0, 500), _span(1, 500, 1000)]
    turns = [_turn(0, 500, "A"), _turn(500, 1000, "B")]
    assert assign_speakers(segments, turns) == {0: "A", 1: "B"}


def test_tong_thoi_luong_noi_theo_speaker_cong_don_nhieu_luot():
    turns = [_turn(0, 300, "A"), _turn(300, 500, "B"), _turn(500, 900, "A")]
    assert total_speech_ms(turns) == {"A": 700, "B": 200}


# ---------------------------------------------------------------------------
# stage.py — DB + I/O (mock backend pyannote, không cần token/model thật)
# ---------------------------------------------------------------------------


def _make_ctx(session, storage, *, source_locale="en-US", target_locale="es-ES"):
    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test", source_locale=source_locale,
    )
    session.add(source)
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale=target_locale)
    session.add(job)
    session.flush()
    transcript = Transcript(
        source_video_id=source.id, locale=source_locale,
        provider="mock", has_word_timestamps=True, full_text="",
    )
    session.add(transcript)
    session.flush()
    for idx, (start, end, text) in enumerate([(0, 500, "xin chao"), (500, 1000, "ban khoe khong")]):
        session.add(STTSegment(transcript_id=transcript.id, idx=idx, start_ms=start, end_ms=end, text=text))
    session.flush()

    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale=target_locale, storage=storage,
    )
    # Stage đọc audio từ SEPARATED trước khi gọi diarization thật — chỉ cần
    # file tồn tại, nội dung không quan trọng vì backend bị mock ở dưới.
    separated = storage.path_for(ArtifactKind.SEPARATED, project_id=project.id)
    (separated / "vocals.wav").write_bytes(b"fake")
    return ctx, source, transcript


def test_bo_qua_khi_thieu_pyannote_khong_chan_pipeline(session, storage):
    """Môi trường test thật sự không cài pyannote.audio — đây chính là kịch
    bản một dev/CI không có HF token sẽ gặp. Stage phải trả succeeded (không
    NonRetryableError) để pipeline chạy tiếp, giữ nguyên hành vi của
    NotImplementedStage cũ (speaker_id luôn None)."""
    ctx, source, transcript = _make_ctx(session, storage)
    result = DiarizeStage().run(ctx, {})

    assert result.output_ref["skipped"] is True
    assert "pyannote" in result.note
    segments = session.query(STTSegment).filter(STTSegment.transcript_id == transcript.id).all()
    assert all(s.speaker_id is None for s in segments), (
        "bỏ qua diarization thì không được để lại speaker_id nửa vời"
    )


def test_gan_speaker_that_khi_backend_san_sang(session, storage, monkeypatch):
    """Giả lập pyannote đã cài + có token bằng cách mock hai hàm biên I/O
    (`check_available`, `run_diarization`) — không kéo theo cài đặt/model
    thật, đúng ranh giới thuần/I-O mà module này theo."""
    ctx, source, transcript = _make_ctx(session, storage)

    monkeypatch.setattr(diarize_stage_module, "check_available", lambda: None)
    monkeypatch.setattr(
        diarize_stage_module,
        "run_diarization",
        lambda *a, **k: [_turn(0, 500, "SPEAKER_00"), _turn(500, 1000, "SPEAKER_01")],
    )

    result = DiarizeStage().run(ctx, {})

    assert result.output_ref == {
        "speakers": 2, "segments_assigned": 2, "segments_total": 2,
        "model": ctx.settings.diarization_model,
    }
    speakers = {s.label: s for s in session.query(Speaker).filter(Speaker.source_video_id == source.id).all()}
    assert set(speakers) == {"SPEAKER_00", "SPEAKER_01"}
    assert speakers["SPEAKER_00"].total_speech_ms == 500

    segs = {
        s.idx: s.speaker_id
        for s in session.query(STTSegment).filter(STTSegment.transcript_id == transcript.id).all()
    }
    assert segs[0] == speakers["SPEAKER_00"].id
    assert segs[1] == speakers["SPEAKER_01"].id


def test_chay_lai_khong_tao_speaker_trung(session, storage, monkeypatch):
    """Idempotent (§11.1): chạy lại diarize trên cùng source không được cộng
    dồn `Speaker` — `_clear_previous` phải gỡ sạch trước khi ghi lại."""
    ctx, source, transcript = _make_ctx(session, storage)
    monkeypatch.setattr(diarize_stage_module, "check_available", lambda: None)
    monkeypatch.setattr(
        diarize_stage_module,
        "run_diarization",
        lambda *a, **k: [_turn(0, 1000, "SPEAKER_00")],
    )

    DiarizeStage().run(ctx, {})
    DiarizeStage().run(ctx, {})

    speakers = session.query(Speaker).filter(Speaker.source_video_id == source.id).all()
    assert len(speakers) == 1, "chạy lại 2 lần phải cho đúng 1 speaker, không phải 2"


def test_cache_params_khong_kem_locale():
    """DIARIZE khai `cache_scope=SOURCE` — kèm locale vào cache_params sẽ vô
    hiệu hoá cache dùng chung giữa các bản dịch (§16, caching.md mục 2)."""
    from core.types import CacheScope

    assert DiarizeStage.cache_scope is CacheScope.SOURCE
