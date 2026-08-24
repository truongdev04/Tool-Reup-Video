"""Khôi phục timing từ audio TTS — docs §8.

Đây là xấp xỉ (rải ký tự đều trong mỗi đoạn có tiếng nói), không phải forced
alignment chính xác cấp phoneme. Test tập trung vào các bất biến PHẢI đúng dù
xấp xỉ tới đâu: đơn điệu tăng, khớp biên đầu/cuối, không vỡ khi thiếu dữ liệu.
"""

from __future__ import annotations

import pytest

from workers.forced_align.aligner import SpeechSpan, char_time_map, span_duration_ms


def test_text_rong_tra_ve_mot_diem():
    assert char_time_map("", [SpeechSpan(0, 1000)], 1000) == [0]


def test_mot_doan_duy_nhat_rai_deu_tuyen_tinh():
    boundaries = char_time_map("0123456789", [SpeechSpan(0, 1000)], 1000)
    assert len(boundaries) == 11
    assert boundaries[0] == 0
    assert boundaries[-1] == 1000
    assert boundaries == [i * 100 for i in range(11)]


def test_khong_co_doan_nao_thi_rai_deu_toan_bo_thoi_luong():
    """STT không nhận ra tiếng nói -> vẫn phải trả kết quả, không được sập."""
    boundaries = char_time_map("hello", [], 500)
    assert boundaries[0] == 0
    assert boundaries[-1] == 500
    assert boundaries == sorted(boundaries), "phải đơn điệu tăng"


def test_bien_dau_cuoi_khop_voi_doan_dau_cuoi():
    """map[0] khớp điểm bắt đầu đoạn đầu; map[n] khớp điểm kết đoạn cuối —
    dù đoạn đầu không bắt đầu tại 0 (vd. có khoảng lặng mở đầu)."""
    spans = [SpeechSpan(200, 600), SpeechSpan(900, 1300)]
    boundaries = char_time_map("abcdefgh", spans, 1500)
    assert boundaries[0] == 200
    assert boundaries[-1] == 1300


def test_luon_don_dieu_tang_du_co_khoang_lang_giua_cac_doan():
    """Bất biến quan trọng nhất: bất kể xấp xỉ ra sao, timestamp không được
    chạy ngược — nếu không cue subtitle sẽ có thời gian âm hoặc chồng lấn."""
    spans = [SpeechSpan(0, 300), SpeechSpan(500, 700), SpeechSpan(1000, 1800)]
    boundaries = char_time_map("một đoạn văn bản khá dài để rải qua ba đoạn", spans, 1800)
    assert boundaries == sorted(boundaries)
    assert len(set(range(len(boundaries)))) == len(boundaries)


def test_ky_tu_trong_doan_dai_hon_duoc_nhieu_thoi_gian_hon():
    """Đoạn dài hơn (nhiều tiếng nói hơn) phải chiếm nhiều ký tự hơn theo tỉ lệ."""
    # Đoạn 1 dài 900ms, đoạn 2 dài 100ms — đoạn 1 gấp 9 lần đoạn 2.
    spans = [SpeechSpan(0, 900), SpeechSpan(1000, 1100)]
    text = "x" * 20
    boundaries = char_time_map(text, spans, 1100)
    # ~90% ký tự (18/20) phải rơi vào đoạn 1.
    chars_in_span0 = sum(1 for i in range(20) if boundaries[i] < 900)
    assert chars_in_span0 >= 17


def test_span_duration_dung_bang_hieu_hai_bien():
    boundaries = char_time_map("0123456789", [SpeechSpan(0, 1000)], 1000)
    assert span_duration_ms(boundaries, 0, 5) == 500
    assert span_duration_ms(boundaries, 5, 10) == 500
    assert span_duration_ms(boundaries, 0, 10) == 1000


def test_khong_bao_gio_tra_ve_am():
    boundaries = char_time_map("ab", [SpeechSpan(100, 100)], 500)  # span rỗng
    assert span_duration_ms(boundaries, 0, 2) >= 0
