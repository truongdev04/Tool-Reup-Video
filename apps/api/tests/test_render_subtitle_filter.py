"""Filter `subtitles` của stage `render` kèm font fallback — docs §13.2, §14.

Chỉ test hàm dựng chuỗi filter (`_subtitles_filter_expr`), không chạy ffmpeg
thật — đã xác nhận filter này chạy được với ffmpeg thật bằng
`scripts/run_pipeline.py` thủ công trong phiên implement (không lặp lại ở
CI vì tốn thời gian mã hoá video không cần thiết cho việc test cú pháp).
"""

from __future__ import annotations

import json
from pathlib import Path

from core.config import Settings
from core.stage import StageContext
from workers.render.stage import _subtitles_filter_expr


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
