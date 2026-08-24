"""Filter `subtitles` + bù offset intro/outro của stage `render` — docs §13.2,
§14, §6.14, §9.

Test hàm dựng chuỗi filter (`_subtitles_filter_expr`, `_audio_sync_filter`,
`_shifted_srt_path`), không chạy ffmpeg thật cho phần filter/audio-sync — đã
xác nhận toàn bộ chuỗi này (kể cả `adelay`/`apad`/SAR) chạy đúng với ffmpeg
thật bằng `scripts/run_pipeline.py` thủ công trong phiên implement, kèm kiểm
tra bằng mắt (trích frame) và đo `volumedetect` xác nhận audio/phụ đề đồng bộ
đúng sau khi có intro/outro (không lặp lại ở CI vì tốn thời gian mã hoá video
không cần thiết cho việc test cú pháp/logic dịch offset)."""

from __future__ import annotations

import json
from pathlib import Path

from core.config import Settings
from core.stage import StageContext
from db.models import Project, RenderJob, SourceVideo, SubtitleCue
from services.branding import IntroOutroDurations
from workers.render.stage import _audio_sync_filter, _shifted_srt_path, _subtitles_filter_expr


def _ctx(storage, *, locale: str, fonts_dir: Path) -> StageContext:
    return StageContext(
        session=None, job_id="job", project_id="proj", source_checksum="c0ffee",
        locale=locale, storage=storage, settings=Settings(fonts_dir=fonts_dir),
    )


def test_co_font_bundle_thi_them_fontsdir_va_force_style(storage, tmp_path):
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    (fonts_dir / "a.ttf").write_bytes(b"fake")
    (fonts_dir / "manifest.json").write_text(json.dumps({"Noto Sans": "a.ttf"}), encoding="utf-8")

    expr = _subtitles_filter_expr(_ctx(storage, locale="en-US", fonts_dir=fonts_dir), Path("/tmp/x.srt"))

    assert "fontsdir=" in expr
    assert "force_style='FontName=Noto Sans'" in expr
    assert expr.startswith("subtitles='/tmp/x.srt'")


def test_khong_co_font_bundle_thi_khong_ep_style(storage, tmp_path):
    """Thiếu font bundle cho locale này không được chặn render — filter vẫn
    hợp lệ, chỉ thiếu 2 tham số, để libass tự chọn font như trước khi có
    tính năng này (§16: bỏ qua, không chặn pipeline)."""
    fonts_dir = tmp_path / "trong"
    fonts_dir.mkdir()

    expr = _subtitles_filter_expr(_ctx(storage, locale="en-US", fonts_dir=fonts_dir), Path("/tmp/x.srt"))

    assert expr == "subtitles='/tmp/x.srt'"


def test_dung_dung_font_that_da_bundle_cho_tung_locale(storage):
    """Dùng `fonts_dir` mặc định thật của repo (không giả lập) — xác nhận
    manifest + font_stack của TỪNG locale hiện có khớp nhau, không lệch tên."""
    settings = Settings()
    ctx_ja = StageContext(
        session=None, job_id="j", project_id="p", source_checksum="c",
        locale="ja-JP", storage=storage, settings=settings,
    )
    ctx_ar = StageContext(
        session=None, job_id="j", project_id="p", source_checksum="c",
        locale="ar-SA", storage=storage, settings=settings,
    )
    assert "force_style='FontName=Noto Sans JP'" in _subtitles_filter_expr(ctx_ja, Path("/tmp/x.srt"))
    assert "force_style='FontName=Noto Sans Arabic'" in _subtitles_filter_expr(ctx_ar, Path("/tmp/x.srt"))


# ---------------------------------------------------------------------------
# _audio_sync_filter — bù intro/outro vào audio đã tái dựng (§6.14, §9)
# ---------------------------------------------------------------------------


def test_khong_intro_van_ep_apad_khop_dung_do_dai_video():
    """Không có intro (intro_ms=0) vẫn phải `apad` khớp đúng độ dài video —
    tin vào video làm mốc thay vì trông cậy `-shortest` cắt vài chục ms lệch
    do làm tròn giữa 2 stream (xem docstring `_audio_sync_filter`)."""
    expr = _audio_sync_filter(IntroOutroDurations(0, 0), video_duration_ms=7000)
    assert expr == "adelay=0:all=1,apad=whole_dur=7.000"


def test_co_intro_dich_dung_so_ms():
    expr = _audio_sync_filter(IntroOutroDurations(intro_ms=1500, outro_ms=1500), video_duration_ms=10000)
    assert expr == "adelay=1500:all=1,apad=whole_dur=10.000"


# ---------------------------------------------------------------------------
# _shifted_srt_path — dịch cue theo intro_ms (§6.14, §8.3)
# ---------------------------------------------------------------------------


def test_shifted_srt_dich_dung_moi_cue_theo_intro_ms(session, storage, tmp_path):
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
    session.add(SubtitleCue(render_job_id=job.id, idx=0, start_ms=0, end_ms=900, lines=["hello"], cps=10.0))
    session.add(SubtitleCue(render_job_id=job.id, idx=1, start_ms=900, end_ms=1800, lines=["world"], cps=10.0))
    session.flush()

    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="en-US", storage=storage,
    )

    out = _shifted_srt_path(ctx, intro_ms=1500, out_dir=tmp_path)
    content = out.read_text(encoding="utf-8")

    assert "00:00:01,500 --> 00:00:02,400" in content, "cue đầu (0-900ms gốc) phải dịch tới sau 1500ms"
    assert "00:00:02,400 --> 00:00:03,300" in content, "cue sau (900-1800ms gốc) phải dịch cùng offset"
