"""Segment Planner — docs §5, §6.6.

Gộp sai thì LLM mất ngữ cảnh và dịch sai; đây là chỗ quyết định chất lượng của
mọi bước sau nên test kỹ.
"""

from __future__ import annotations

import pytest

from services.presets import available_locales, load_locale
from workers.segment_planner.planner import (
    MAX_UNIT_CHARS,
    RawSegment,
    merge_to_units,
    plan,
)


@pytest.fixture
def en():
    return load_locale("en-US")


@pytest.fixture
def es():
    return load_locale("es-ES")


@pytest.fixture
def ja():
    return load_locale("ja-JP")


def _seg(idx, start, end, text, speaker="S1"):
    return RawSegment(idx=idx, start_ms=start, end_ms=end, text=text, speaker=speaker)


def test_gop_manh_vun_thanh_cau_tron_nghia(en):
    """STT cắt theo khoảng lặng nên hay cắt giữa câu — phải gộp lại (§5)."""
    segments = [
        _seg(0, 0, 800, "This tool takes one video"),
        _seg(1, 850, 1600, "and turns it into"),
        _seg(2, 1650, 2400, "many language versions."),
    ]
    units = merge_to_units(segments, source_preset=en)

    assert len(units) == 1, "ba mảnh của cùng một câu phải thành một đơn vị dịch"
    assert units[0].text == "This tool takes one video and turns it into many language versions."
    assert units[0].start_ms == 0
    assert units[0].end_ms == 2400
    assert units[0].source_segment_idxs == [0, 1, 2]


def test_tach_theo_dau_ket_cau(en):
    segments = [
        _seg(0, 0, 900, "First sentence here."),
        _seg(1, 950, 1800, "Second sentence here."),
    ]
    units = merge_to_units(segments, source_preset=en)
    assert len(units) == 2


def test_khoang_lang_dai_cat_don_vi_du_khong_co_dau_cau(en):
    """STT thường bỏ dấu câu ở cuối đoạn, nên không thể chỉ dựa vào dấu."""
    segments = [
        _seg(0, 0, 900, "no punctuation here"),
        _seg(1, 3000, 3900, "clearly a new thought"),
    ]
    units = merge_to_units(segments, source_preset=en)
    assert len(units) == 2, "khoảng lặng 2.1s phải được coi là ranh giới câu"


def test_khong_bao_gio_gop_loi_hai_nguoi(en):
    segments = [
        _seg(0, 0, 900, "are you coming", speaker="S1"),
        _seg(1, 920, 1800, "yes I am", speaker="S2"),
    ]
    units = merge_to_units(segments, source_preset=en)
    assert len(units) == 2
    assert units[0].speaker == "S1"
    assert units[1].speaker == "S2"


def test_chan_tran_ky_tu(en):
    """Đơn vị quá dài khiến LLM tóm tắt thay vì dịch, và budget mất tác dụng."""
    long_text = "word " * 60  # 300 ký tự, không có dấu kết câu
    segments = [_seg(i, i * 500, i * 500 + 450, long_text) for i in range(3)]
    units = merge_to_units(segments, source_preset=en)

    assert len(units) > 1
    for u in units:
        assert len(u.text) <= MAX_UNIT_CHARS * 2, "vượt trần ký tự quá xa"


def test_khong_bo_sot_noi_dung(en):
    """Segment cuối không có dấu chấm vẫn phải được ghi nhận."""
    segments = [
        _seg(0, 0, 900, "First sentence."),
        _seg(1, 950, 1800, "trailing text without period"),
    ]
    units = merge_to_units(segments, source_preset=en)
    assert "trailing text without period" in " ".join(u.text for u in units)


def test_budget_khac_nhau_theo_ngon_ngu_dich(en, es, ja):
    """Cùng một đoạn 4s: tiếng Nhật phải được budget ký tự NHỎ hơn nhiều so với
    tiếng Tây Ban Nha, vì mỗi ký tự CJK mang nhiều thông tin hơn (§5, §7.2)."""
    segments = [_seg(0, 0, 4000, "This is a four second sentence.")]

    es_units = plan(segments, source_preset=en, target_preset=es)
    ja_units = plan(segments, source_preset=en, target_preset=ja)

    assert es_units[0].char_budget == pytest.approx(56, abs=2)
    assert ja_units[0].char_budget == pytest.approx(28, abs=2)
    assert ja_units[0].char_budget < es_units[0].char_budget


def test_danh_dau_hook_va_cta(en, es):
    """Hook và CTA phải dịch thoáng, không dịch sát (§6.7)."""
    segments = [
        _seg(0, 0, 2000, "Stop scrolling right now."),
        _seg(1, 5000, 8000, "Here is the middle part."),
        _seg(2, 15000, 18000, "Follow for more tips."),
    ]
    units = plan(segments, source_preset=en, target_preset=es)

    assert units[0].needs_transcreation, "hook phải được đánh dấu"
    assert units[-1].needs_transcreation, "CTA phải được đánh dấu"
    assert not units[1].needs_transcreation, "đoạn giữa dịch sát là được"


def test_preset_cjk_va_rtl_khai_bao_dung():
    ja, ar = load_locale("ja-JP"), load_locale("ar-SA")
    assert ja.is_cjk and not ja.is_rtl
    assert ar.is_rtl
    assert ja.chars_per_line < ar.chars_per_line, "CJK phải ít ký tự/dòng hơn"
    assert "Noto Sans JP" in ja.font_stack, "thiếu font có glyph CJK -> ra ô vuông"


def test_locale_thieu_bao_loi_ro_rang():
    from services.presets import PresetNotFound

    with pytest.raises(PresetNotFound, match="Đang có"):
        load_locale("xx-XX")


def test_speech_rate_chua_hieu_chuan_duoc_danh_dau():
    """Số liệu tốc độ đọc hiện là ước lượng — sai số đẩy thẳng vào drift.
    Phải đo lại sau khi chốt provider TTS (§23 #3)."""
    for loc in available_locales():
        preset = load_locale(loc)
        assert not preset.speech_rate_calibrated, (
            f"{loc} tự nhận đã hiệu chuẩn — chỉ được set cờ này sau khi đo bằng TTS thật"
        )
