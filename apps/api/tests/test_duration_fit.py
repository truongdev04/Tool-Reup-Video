"""Duration Fitting — docs §7.

Bài toán khó nhất của dubbing và là lỗ hổng lớn nhất của kế hoạch v2. Test theo
đúng thang ưu tiên §7.2: rẻ và ít hại nhất trước.
"""

from __future__ import annotations

import pytest

from core.types import FitStrategy
from workers.duration_fit.fitter import (
    FitInput,
    FitPolicy,
    accumulate_drift,
    decide,
)

POLICY = FitPolicy()
RATE = 14.0  # es-ES speech_rate_cps


def _decide(target, actual, **kw):
    return decide(
        FitInput(target_duration_ms=target, actual_duration_ms=actual, **kw),
        policy=POLICY, speech_rate_cps=RATE,
    )


def test_trong_sai_so_thi_khong_lam_gi():
    d = _decide(6000, 6200, translate_attempts=2)
    assert d.strategy is FitStrategy.NONE
    assert d.tempo_ratio == 1.0


def test_uu_tien_1_dich_lai_co_rang_buoc():
    """Chiến lược rẻ nhất và chất lượng cao nhất — luôn thử trước (§7.2)."""
    d = _decide(6000, 7400)
    assert d.strategy is FitStrategy.CONSTRAINED_TRANSLATION
    assert d.retry_char_budget == round(6000 / 1000 * RATE)
    assert d.tempo_ratio == 1.0, "chưa được đụng tới tốc độ đọc ở bước này"


def test_het_luot_dich_moi_leo_len_bac_sau():
    d = _decide(6000, 7400, translate_attempts=2)
    assert d.strategy is not FitStrategy.CONSTRAINED_TRANSLATION


def test_uu_tien_2_an_vao_khoang_lang():
    """Mượn im lặng thì không phải đụng tới giọng đọc — ưu tiên hơn tempo."""
    d = _decide(6000, 6900, available_silence_ms=1200, translate_attempts=2)
    assert d.strategy is FitStrategy.BORROW_SILENCE
    assert d.borrow_silence_ms == 900
    assert d.drift_ms == 0
    assert d.tempo_ratio == 1.0


def test_muon_mot_phan_roi_tempo_xu_ly_phan_con_lai():
    """Silence không đủ: mượn hết phần có, phần dư để tempo gánh."""
    d = _decide(6000, 6900, available_silence_ms=400, translate_attempts=2)
    assert d.strategy is FitStrategy.TEMPO_ADJUST
    assert d.borrow_silence_ms == 400
    # khung = 6000 + 400 = 6400 -> ratio = 6900/6400 = 1.078, vẫn trong ngưỡng
    assert d.tempo_ratio == pytest.approx(6900 / 6400, abs=1e-3)


def test_uu_tien_3_tempo_trong_nguong_an_toan():
    d = _decide(6000, 6450, translate_attempts=2)
    assert d.strategy is FitStrategy.TEMPO_ADJUST
    assert POLICY.tempo_min <= d.tempo_ratio <= POLICY.tempo_max
    assert d.drift_ms == 0


def test_tempo_vuot_nguong_thi_khong_dung():
    """Ngoài 0,92–1,08 là tai người nghe ra ngay — thà leo lên bậc sau (§7.2)."""
    d = _decide(6000, 7400, translate_attempts=2)
    assert d.strategy is not FitStrategy.TEMPO_ADJUST


def test_uu_tien_4_co_gian_hinh_khi_khong_co_mat_nguoi():
    d = _decide(6000, 7400, translate_attempts=2, has_face=False)
    assert d.strategy is FitStrategy.VIDEO_STRETCH
    assert d.video_adjust_ms == 1400


def test_co_mat_nguoi_thi_cam_co_gian_hinh():
    """Co giãn hình khi có mặt người sẽ phá lip-sync — phải chuyển manual review."""
    d = _decide(6000, 7400, translate_attempts=2, has_face=True)
    assert d.strategy is FitStrategy.MANUAL_REVIEW
    assert d.needs_manual_review
    assert "mặt người" in d.reason


def test_khong_ep_duoc_thi_danh_dau_chu_khong_ep_bua():
    policy = FitPolicy(allow_video_stretch=False)
    d = decide(
        FitInput(target_duration_ms=6000, actual_duration_ms=9000, translate_attempts=2),
        policy=policy, speech_rate_cps=RATE,
    )
    assert d.strategy is FitStrategy.MANUAL_REVIEW
    assert d.tempo_ratio == 1.0, "không được âm thầm áp tempo ngoài ngưỡng"


def test_doc_ngan_hon_khung_hinh_cung_duoc_xu_ly():
    """EN -> JA thường co lại, không phải lúc nào cũng dài ra."""
    d = _decide(6000, 4800, translate_attempts=2)
    assert d.strategy in (FitStrategy.TEMPO_ADJUST, FitStrategy.VIDEO_STRETCH,
                          FitStrategy.MANUAL_REVIEW)
    assert d.strategy is not FitStrategy.BORROW_SILENCE, "đọc ngắn thì mượn im lặng vô nghĩa"


def test_fitter_tu_chan_khong_de_drift_don_qua_nguong():
    """Chỉ số QC quan trọng nhất của hệ thống (§15, DoD §21).

    Mỗi đơn vị chỉ lệch 240ms — thừa sức nằm trong dung sai 10%. Nếu xét từng
    đơn vị một cách độc lập thì cả 8 đều được cho qua và audio trôi 1.920ms.
    Fitter phải soi vào drift tích luỹ và can thiệp trước khi vỡ ngân sách.
    """
    decisions = []
    cumulative = 0
    for _ in range(8):
        d = _decide(6000, 6240, translate_attempts=2, cumulative_drift_ms=cumulative)
        decisions.append(d)
        cumulative += d.drift_ms

    assert abs(cumulative) <= POLICY.max_cumulative_drift_ms, (
        f"drift dồn tới {cumulative}ms, vượt ngân sách {POLICY.max_cumulative_drift_ms}ms"
    )
    assert any(d.strategy is not FitStrategy.NONE for d in decisions), (
        "phải có ít nhất một đơn vị bị can thiệp để kéo drift về"
    )


def test_don_vi_le_nho_van_duoc_bo_qua_khi_tong_con_du_ngan_sach():
    """Không được can thiệp bừa: lệch nhỏ mà tổng còn dư thì cứ để yên."""
    d = _decide(6000, 6100, translate_attempts=2, cumulative_drift_ms=0)
    assert d.strategy is FitStrategy.NONE


def test_da_co_drift_thi_don_vi_sau_phai_doc_bu_nguoc():
    """Đã trôi +280ms thì đơn vị này phải ngắn lại để kéo tổng về 0."""
    d = _decide(6000, 6100, translate_attempts=0, cumulative_drift_ms=280)
    assert d.strategy is FitStrategy.CONSTRAINED_TRANSLATION
    # budget tính theo khung đã trừ drift: 6000 - 280 = 5720ms
    assert d.retry_char_budget == round(5720 / 1000 * RATE)


def test_fit_thanh_cong_keo_tong_drift_ve_khong():
    d = _decide(6000, 6450, translate_attempts=2, cumulative_drift_ms=250)
    assert d.strategy is not FitStrategy.NONE
    assert 250 + d.drift_ms == 0, "sau khi fit, drift tích luỹ phải về 0"


def test_chien_luoc_thanh_cong_khong_de_lai_drift():
    for d in (
        _decide(6000, 6900, available_silence_ms=1200, translate_attempts=2),
        _decide(6000, 6450, translate_attempts=2),
        _decide(6000, 7400, translate_attempts=2),
    ):
        assert d.drift_ms == 0, f"{d.strategy} phải khử hết lệch, không để dồn"
