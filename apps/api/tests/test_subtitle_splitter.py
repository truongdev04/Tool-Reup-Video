"""Cắt cue subtitle theo giới hạn đọc — docs §6.11, §8."""

from __future__ import annotations

import pytest

from services.presets import load_locale
from workers.subtitle.splitter import split_unit_into_cues


def _uniform_boundaries(text: str, total_ms: int) -> list[int]:
    """Timing giả lập: mỗi ký tự chiếm thời gian bằng nhau — đủ để test logic
    cắt cue mà không cần forced_align thật."""
    n = len(text)
    return [round(i / n * total_ms) for i in range(n + 1)] if n else [0]


@pytest.fixture
def en():
    return load_locale("en-US")  # chars_per_line=42, max_lines=2, cps_max=20


@pytest.fixture
def ja():
    return load_locale("ja-JP")  # chars_per_line=16, max_lines=2, cps_max=9, cjk


def test_cau_ngan_ra_dung_mot_cue(en):
    text = "Stop scrolling right now."
    boundaries = _uniform_boundaries(text, 2000)  # 26 ký tự / 2s = 13 cps, dưới cps_max
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=1000, preset=en)

    assert len(cues) == 1
    assert cues[0].lines == [text]
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 3000


def test_timestamp_la_tuyet_doi_theo_unit_start(en):
    text = "Hello world"
    boundaries = _uniform_boundaries(text, 1000)
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=5000, preset=en)
    assert cues[0].start_ms >= 5000


def test_qua_dai_mot_dong_thi_xuong_dong_thu_hai(en):
    # 9 từ ~64 ký tự — vượt 1 dòng (42) nhưng vừa 2 dòng (84).
    text = "alpha bravo charlie delta echo foxtrot golf hotel india"
    boundaries = _uniform_boundaries(text, 4500)  # ~64 ký tự / 4.5s ~ 14 cps, an toàn
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)

    assert len(cues) == 1, "vẫn vừa trong 2 dòng nên chỉ 1 cue"
    assert len(cues[0].lines) == 2
    for line in cues[0].lines:
        assert len(line) <= en.chars_per_line


def test_vuot_qua_max_lines_thi_tach_cue_moi(en):
    # Text đủ dài để cần hơn 2 dòng -> phải tách thành nhiều cue.
    text = " ".join(f"word{i}" for i in range(20))  # ~140 ký tự
    boundaries = _uniform_boundaries(text, 6000)  # ~23 cps — hơi nhanh nhưng tách theo dòng trước
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)

    assert len(cues) > 1
    for cue in cues:
        assert len(cue.lines) <= en.max_lines


def test_doc_qua_nhanh_va_du_dai_thi_van_bi_tach(en):
    """Đọc quá nhanh phải bị tách — NHƯNG chỉ sau khi cue đã đủ dài để đứng
    một mình (>= min_cue_ms), không tách ngay từ cặp từ đầu tiên."""
    text = "one two three four five six seven eight nine ten"
    boundaries = _uniform_boundaries(text, 1800)  # ~27 cps >> cps_max=20, đủ dài để tách được
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)

    assert len(cues) > 1, "đủ thời lượng để tách thành nhiều cue nhằm hạ CPS"
    for cue in cues[:-1]:  # cue cuối có thể ngắn hơn min_cue_ms, không tính
        assert cue.end_ms - cue.start_ms >= en.min_cue_ms


def test_doc_nhanh_nhung_qua_ngan_thi_khong_the_tach(en):
    """Toàn bộ unit ngắn hơn min_cue_ms: không cách nào tách ra một cue hợp lệ
    đứng một mình — thà một cue hơi nhanh còn hơn nhiều cue lập loè dưới
    ngưỡng đọc được. Đây là tình huống thực tế phổ biến: TTS đọc nhanh hơn
    ngưỡng đọc thoải mái của phụ đề (§7 vs §6.11 xung đột nhau)."""
    text = "one two three four five six seven eight nine ten"
    boundaries = _uniform_boundaries(text, 1000)  # đúng bằng min_cue_ms, không dư ra để tách
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)
    assert len(cues) == 1
    assert cues[0].cps > en.cps_max, "chấp nhận vượt CPS còn hơn vỡ vụn thành cue 1 từ"


def test_mot_atom_duy_nhat_khong_the_tach_them(en):
    """Một từ vượt cps_max một mình thì chấp nhận, không có cách nào chia nhỏ hơn."""
    text = "supercalifragilisticexpialidocious"
    boundaries = _uniform_boundaries(text, 200)  # cực nhanh, không cách nào tránh
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)
    assert len(cues) == 1
    assert cues[0].lines == [text]


def test_khong_bo_sot_noi_dung(en):
    text = "one two three four five six seven eight nine ten eleven twelve"
    boundaries = _uniform_boundaries(text, 8000)
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)

    rebuilt = " ".join(" ".join(cue.lines) for cue in cues)
    for word in text.split():
        assert word in rebuilt


def test_cue_qua_ngan_duoc_keo_dai_toi_min_cue_ms(en):
    """Câu quá ngắn: người xem cần thời gian ĐỌC nhiều hơn thời gian audio NÓI.
    Caller phải cho biết còn bao nhiêu chỗ trống trước lời thoại kế tiếp —
    không có audio nào tự "biết" khi nào nó được phép kéo dài quá chính nó."""
    text = "Hi."
    boundaries = _uniform_boundaries(text, 100)  # cực ngắn
    cues = split_unit_into_cues(
        text, boundaries, unit_start_ms=0, preset=en, display_end_limit_ms=5000
    )
    assert cues[0].end_ms - cues[0].start_ms >= en.min_cue_ms


def test_khong_co_gioi_han_hien_thi_thi_khong_vuot_qua_audio(en):
    """Không truyền display_end_limit_ms -> an toàn mặc định: không lấn vào
    khoảng đáng lẽ thuộc về unit kế tiếp."""
    text = "Hi."
    boundaries = _uniform_boundaries(text, 100)
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)
    assert cues[0].end_ms == 100


def test_gioi_han_hien_thi_qua_gan_thi_khong_keo_dai_duoc_het(en):
    """Có giới hạn nhưng không đủ chỗ — kéo dài tới giới hạn, không hơn."""
    text = "Hi."
    boundaries = _uniform_boundaries(text, 100)
    cues = split_unit_into_cues(
        text, boundaries, unit_start_ms=0, preset=en, display_end_limit_ms=300
    )
    assert cues[0].end_ms == 300


def test_keo_dai_khong_vuot_qua_cue_ke_tiep(en):
    text = "Hi. This is a much longer second sentence that follows right after."
    # Câu đầu cực ngắn, câu sau chiếm gần hết -> cue đầu không được lấn cue sau.
    boundaries = _uniform_boundaries(text, 4000)
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=en)
    if len(cues) > 1:
        assert cues[0].end_ms <= cues[1].start_ms


def test_cjk_tach_theo_ky_tu_khong_theo_khoang_trang(ja):
    text = "このツールは動画を多言語に変換します"
    boundaries = _uniform_boundaries(text, 4000)  # 18 ký tự / 4s = 4.5cps, dưới cps_max=9
    cues = split_unit_into_cues(text, boundaries, unit_start_ms=0, preset=ja)

    assert len(cues) >= 1
    rebuilt = "".join("".join(cue.lines) for cue in cues)
    assert rebuilt.replace("\n", "") == text.replace(" ", "")
    for cue in cues:
        for line in cue.lines:
            assert len(line) <= ja.chars_per_line


def test_text_rong_tra_ve_rong(en):
    assert split_unit_into_cues("", [0], 0, en) == []
