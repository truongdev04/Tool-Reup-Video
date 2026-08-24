"""Font fallback cho hardsub — docs §13.2, §14.

`services/fonts.py::resolve()` là module thuần (nhận `fonts_dir` làm tham số,
test bằng thư mục giả). `missing_glyphs()` đo THẬT trên bộ font Noto đã bundle
trong `apps/api/assets/fonts/` — dùng chính font sẽ lên hình, không giả lập,
để test này thật sự bắt được font bundle bị thiếu/hỏng.
"""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings
from services.fonts import resolve
from services.qc_media import missing_glyphs
from workers.qc.checks import check_font_coverage


# ---------------------------------------------------------------------------
# resolve() — module thuần, thư mục font giả
# ---------------------------------------------------------------------------


def _fake_fonts_dir(tmp_path: Path, manifest: dict[str, str]) -> Path:
    d = tmp_path / "fonts"
    d.mkdir()
    for filename in manifest.values():
        (d / filename).write_bytes(b"fake-font-bytes")
    import json

    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_chon_family_dau_tien_trong_stack_co_file_that(tmp_path):
    fonts_dir = _fake_fonts_dir(tmp_path, {"Noto Sans": "a.ttf", "Noto Sans JP": "b.ttf"})
    result = resolve(("Noto Sans JP", "Noto Sans"), fonts_dir)
    assert result.primary_family == "Noto Sans JP", (
        "phải giữ đúng THỨ TỰ ưu tiên trong font_stack, không phải thứ tự trong manifest"
    )


def test_family_dau_khong_co_file_thi_lay_family_ke_tiep(tmp_path):
    fonts_dir = _fake_fonts_dir(tmp_path, {"Noto Sans": "a.ttf"})
    result = resolve(("Noto Sans Arabic", "Noto Sans"), fonts_dir)
    assert result.primary_family == "Noto Sans", "family đầu không có file thì bỏ qua, thử family sau"


def test_khong_family_nao_co_file_thi_rong_khong_ep_force_style(tmp_path):
    """Thiếu font bundle không được chặn render — để libass tự chọn như hành
    vi trước khi có tính năng này (§16: bỏ qua, không chặn pipeline)."""
    fonts_dir = _fake_fonts_dir(tmp_path, {})
    result = resolve(("Noto Sans",), fonts_dir)
    assert result.primary_family == ""
    assert result.available == {}


def test_font_stack_rong_thi_khong_co_primary():
    result = resolve((), Path("/khong-ton-tai"))
    assert result.primary_family == ""


def test_thu_muc_khong_co_manifest_thi_coi_nhu_chua_cau_hinh(tmp_path):
    empty = tmp_path / "trong"
    empty.mkdir()
    result = resolve(("Noto Sans",), empty)
    assert result.available == {}


# ---------------------------------------------------------------------------
# missing_glyphs() — đo THẬT trên font Noto đã bundle trong repo
# ---------------------------------------------------------------------------


def _bundled_font_paths() -> list[Path]:
    fonts_dir = get_settings().fonts_dir
    return [
        fonts_dir / "NotoSans-Regular.ttf",
        fonts_dir / "NotoSansJP-Regular.ttf",
        fonts_dir / "NotoSansArabic-Regular.ttf",
    ]


def test_tieng_anh_co_ban_duoc_phu_day_du():
    assert missing_glyphs("Hello, world!", _bundled_font_paths()) == set()


def test_tieng_viet_co_dau_duoc_noto_sans_phu():
    """vi-VN dùng chung 'Noto Sans' (font_stack) — thiếu dấu là câu vô nghĩa,
    không chỉ là ô vuông lẻ tẻ."""
    assert missing_glyphs("Xin chào, đây là phụ đề tiếng Việt", _bundled_font_paths()) == set()


def test_tieng_nhat_duoc_noto_sans_jp_phu():
    assert missing_glyphs("日本語のテスト字幕です", _bundled_font_paths()) == set()


def test_tieng_a_rap_duoc_noto_sans_arabic_phu():
    assert missing_glyphs("اختبار الترجمة العربية", _bundled_font_paths()) == set()


def test_ky_tu_khong_font_nao_phu_bi_phat_hien():
    """Chữ Cherokee không nằm trong cả 3 font đã bundle — phải bắt được, không
    được bỏ sót (đây là đúng lý do check này tồn tại). Lặp lại cùng một ký tự
    để xác nhận kết quả cũng khử trùng lặp (set), không đếm theo lần xuất hiện."""
    missing = missing_glyphs("ꭰꭰ", _bundled_font_paths())
    assert missing == {"ꭰ"}


def test_khong_font_nao_thi_moi_ky_tu_khong_phai_dau_cach_deu_thieu():
    assert missing_glyphs("abc", []) == {"a", "b", "c"}


def test_khoang_trang_va_dau_cau_co_ban_khong_tinh_la_thieu():
    assert missing_glyphs("  ...!?", []) == set()


# ---------------------------------------------------------------------------
# check_font_coverage() — luật quyết định thuần
# ---------------------------------------------------------------------------


def test_khong_thieu_glyph_thi_pass():
    finding = check_font_coverage([])
    assert finding.verdict.value == "pass"


def test_thieu_glyph_thi_fail_khong_phai_warn():
    """Ô vuông trên hình là lỗi nhìn thấy ngay — không có mức 'chấp nhận
    được' như cue_cps."""
    finding = check_font_coverage(["Ꭰ", "Ꭱ"])
    assert finding.verdict.value == "fail"
    assert "2" in finding.message
