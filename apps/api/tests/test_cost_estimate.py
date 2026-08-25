"""`services/cost_estimate.py` — ước tính chi phí trước batch (§17.1).

Nguyên tắc kiểm: ưu tiên số liệu THẬT (`ApiUsage.is_estimate=False`) khi có,
chỉ rơi về giá niêm yết/heuristic khi chưa có lịch sử — test khoá cả hai
nhánh để không ai vô tình đảo thứ tự ưu tiên.
"""

from __future__ import annotations

from core.types import JobStatus, StageName
from db.models import ApiUsage, Project, RenderJob, SourceVideo, StageRun, Transcript
from services.cost_estimate import estimate_batch


def _project_with_video(session, *, filename="a.mp4", duration_ms=60_000, source_locale=None):
    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename=filename, storage_path=filename,
        checksum=f"c-{filename}", rights_note="test",
        media_info={"duration_ms": duration_ms}, source_locale=source_locale,
    )
    session.add(source)
    session.flush()
    return project, source


def test_chua_transcribe_thi_uoc_ky_tu_tho_theo_thoi_luong_va_bao_warning(session):
    """Video chưa qua STT — không có `Transcript.full_text` — phải suy đoán từ
    `duration_ms`, và PHẢI cảnh báo đây là số thô, không phải số đo."""
    _, source = _project_with_video(session, duration_ms=60_000)

    result = estimate_batch(
        session, source_videos=[source], target_locales=["es-ES"],
        translation_provider_id="mock", tts_provider_id="macos_say",
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_chars_measured is False
    assert item.source_chars > 0
    assert any("chưa có transcript" in w for w in result.warnings)


def test_da_transcribe_thi_dung_dung_so_ky_tu_that(session):
    """Có `Transcript.full_text` thật — PHẢI dùng đúng `len(full_text)`, không
    suy đoán lại từ duration (số đo thật luôn ưu tiên hơn heuristic)."""
    _, source = _project_with_video(session, duration_ms=60_000)
    text = "xin chào " * 20
    session.add(Transcript(source_video_id=source.id, locale="vi-VN", provider="mock", full_text=text))
    session.flush()

    result = estimate_batch(
        session, source_videos=[source], target_locales=["es-ES"],
        translation_provider_id="mock", tts_provider_id="macos_say",
    )

    item = result.items[0]
    assert item.source_chars_measured is True
    assert item.source_chars == len(text)
    assert not any("chưa có transcript" in w for w in result.warnings)


def test_uu_tien_lich_su_usage_that_hon_gia_niem_yet(session):
    """Có `ApiUsage` thật (is_estimate=False) của ĐÚNG provider — phải dùng
    cost/char đo thực tế đó, không quay lại ước tính token≈ký_tự/4."""
    project, source = _project_with_video(session, duration_ms=10_000)
    session.add(Transcript(source_video_id=source.id, locale="en-US", provider="mock", full_text="a" * 100))
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="es-ES")
    session.add(job)
    session.flush()
    # Lịch sử thật: provider "mock" từng dịch 100 ký tự tốn 0.01 USD.
    session.add(ApiUsage(
        render_job_id=job.id, stage=StageName.TRANSLATE, provider="mock",
        characters=100, cost_usd=0.01, is_estimate=False,
    ))
    session.flush()

    result = estimate_batch(
        session, source_videos=[source], target_locales=["ja-JP"],
        translation_provider_id="mock", tts_provider_id="macos_say",
    )

    item = result.items[0]
    # cost/char lịch sử = 0.01/100 = 0.0001; translated_chars ước = 100 (≈ nguồn)
    assert abs(item.translation_cost_usd - 0.0001 * item.translated_chars_estimate) < 1e-9


def test_da_chay_thanh_cong_truoc_do_thi_danh_dau_already_done(session):
    """(video, locale) đã có TRANSLATE + TTS thành công — cache-hit khi chạy
    lại (§16), gần như không tốn thêm tiền — phải đánh dấu `already_done`."""
    project, source = _project_with_video(session)
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="es-ES")
    session.add(job)
    session.flush()
    for stage in (StageName.TRANSLATE, StageName.TTS):
        session.add(StageRun(
            render_job_id=job.id, stage=stage, status=JobStatus.SUCCEEDED,
            input_hash="h" * 64,
        ))
    session.flush()

    result = estimate_batch(
        session, source_videos=[source], target_locales=["es-ES"],
        translation_provider_id="mock", tts_provider_id="macos_say",
    )

    assert result.items[0].already_done is True


def test_video_locale_chua_chay_thi_khong_danh_dau_already_done(session):
    _, source = _project_with_video(session)

    result = estimate_batch(
        session, source_videos=[source], target_locales=["es-ES"],
        translation_provider_id="mock", tts_provider_id="macos_say",
    )

    assert result.items[0].already_done is False


def test_provider_khong_ton_tai_thi_bao_warning_khong_crash(session):
    """Provider dịch/TTS gõ sai tên — không được để ước tính vỡ giữa chừng,
    phải trả 0 chi phí + cảnh báo (cùng nguyên tắc 'bỏ qua, không chặn' của
    compose/diarize)."""
    _, source = _project_with_video(session)

    result = estimate_batch(
        session, source_videos=[source], target_locales=["es-ES"],
        translation_provider_id="khong-ton-tai", tts_provider_id="cung-khong-ton-tai",
    )

    item = result.items[0]
    assert item.translation_cost_usd == 0.0
    assert item.tts_cost_usd == 0.0
    assert any("không nạp được provider dịch" in w for w in result.warnings)
    assert any("không nạp được provider TTS" in w for w in result.warnings)


def test_provider_chua_khai_gia_thi_bao_warning_khong_lam_nhu_mien_phi(session):
    """`usd_per_1m_input`/`usd_per_1m_output` = None (chưa ai điền giá, vd.
    openai/claude hiện tại) PHẢI khác `0.0` (free thật, vd. mock/ollama) —
    trả `$0.0000` mà không cảnh báo sẽ khiến người xem tưởng nhầm là free."""
    _, source = _project_with_video(session)
    session.add(Transcript(source_video_id=source.id, locale="en-US", provider="mock", full_text="a" * 40))
    session.flush()

    result = estimate_batch(
        session, source_videos=[source], target_locales=["es-ES"],
        translation_provider_id="openai", tts_provider_id="macos_say",
    )

    assert result.items[0].translation_cost_usd == 0.0
    assert any("chưa khai `usd_per_1m_input`" in w for w in result.warnings)


def test_tong_hop_dung_bang_tong_tung_item(session):
    """`total_cost_usd`/`total_tts_audio_seconds` phải khớp tổng từng dòng —
    tránh lệch khi có ai đó sửa property mà quên đồng bộ."""
    _, v1 = _project_with_video(session, filename="v1.mp4")
    _, v2 = _project_with_video(session, filename="v2.mp4")

    result = estimate_batch(
        session, source_videos=[v1, v2], target_locales=["es-ES", "ja-JP"],
        translation_provider_id="mock", tts_provider_id="macos_say",
    )

    assert len(result.items) == 4  # 2 video × 2 locale
    assert result.total_cost_usd == sum(i.translation_cost_usd + i.tts_cost_usd for i in result.items)
    assert result.total_tts_audio_seconds == sum(i.tts_audio_seconds_estimate for i in result.items)
