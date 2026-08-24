"""Luật quyết định QC — docs §15. Không cần video/audio thật, chỉ số liệu."""

from __future__ import annotations

from core.types import QCVerdict
from workers.qc.checks import (
    check_background_retained,
    check_cue_cps,
    check_cue_overlap,
    check_cumulative_drift,
    check_forced_alignment_used,
    check_loudness,
    check_no_clipping,
    check_output_playable,
    check_tempo_bounds,
    check_translation_completeness,
    overall_verdict,
)


def test_drift_trong_nguong_thi_pass():
    assert check_cumulative_drift(250, max_drift_ms=300).verdict is QCVerdict.PASS


def test_drift_vuot_nguong_thi_fail():
    f = check_cumulative_drift(450, max_drift_ms=300)
    assert f.verdict is QCVerdict.FAIL
    assert "450" in f.message


def test_drift_am_cung_tinh_theo_gia_tri_tuyet_doi():
    assert check_cumulative_drift(-450, max_drift_ms=300).verdict is QCVerdict.FAIL


def test_khong_co_cue_nao_la_fail():
    f = check_forced_alignment_used(0, True)
    assert f.verdict is QCVerdict.FAIL


def test_co_cue_khong_tu_forced_align_la_fail():
    f = check_forced_alignment_used(5, False)
    assert f.verdict is QCVerdict.FAIL


def test_du_cue_va_tu_forced_align_la_pass():
    assert check_forced_alignment_used(5, True).verdict is QCVerdict.PASS


def test_cue_khong_chong_lan_la_pass():
    cues = [(0, 1000), (1000, 2000), (2500, 3000)]
    assert check_cue_overlap(cues).verdict is QCVerdict.PASS


def test_cue_chong_lan_la_fail():
    cues = [(0, 1000), (900, 2000)]
    f = check_cue_overlap(cues)
    assert f.verdict is QCVerdict.FAIL
    assert "900" in f.message


def test_cue_khong_can_theo_thu_tu_dau_vao():
    """Hàm phải tự sắp xếp lại, không giả định input đã sorted."""
    cues = [(1000, 2000), (0, 1000)]
    assert check_cue_overlap(cues).verdict is QCVerdict.PASS


def test_cps_trong_nguong_la_pass():
    assert check_cue_cps([10.0, 15.0], cps_max=17.0).verdict is QCVerdict.PASS


def test_cps_vuot_nhe_la_warn_khong_phai_fail():
    """Vượt nhẹ được CHẤP NHẬN có chủ ý (§6.11) — không được chặn QC."""
    f = check_cue_cps([20.0], cps_max=17.0, hard_ceiling_ratio=1.5)
    assert f.verdict is QCVerdict.WARN


def test_cps_vuot_xa_la_fail():
    f = check_cue_cps([30.0], cps_max=17.0, hard_ceiling_ratio=1.5)
    assert f.verdict is QCVerdict.FAIL


def test_tempo_trong_nguong_la_pass():
    assert check_tempo_bounds([1.0, 1.05, 0.95], tempo_min=0.92, tempo_max=1.08).verdict is QCVerdict.PASS


def test_tempo_ngoai_nguong_la_fail():
    """Không thể xảy ra bình thường — fitter đã chặn. FAIL ở đây = có bug thật."""
    f = check_tempo_bounds([1.0, 1.5], tempo_min=0.92, tempo_max=1.08)
    assert f.verdict is QCVerdict.FAIL
    assert "bug" in f.message


def test_thieu_ban_dich_la_fail():
    f = check_translation_completeness(units_total=5, translations_present=3)
    assert f.verdict is QCVerdict.FAIL
    assert "câm" in f.message


def test_du_ban_dich_la_pass():
    assert check_translation_completeness(5, 5).verdict is QCVerdict.PASS


def test_khong_co_unit_nao_la_fail():
    assert check_translation_completeness(0, 0).verdict is QCVerdict.FAIL


def test_output_du_dieu_kien_la_pass():
    f = check_output_playable(
        duration_ms=7000, expected_duration_ms=7000,
        has_audio=True, has_video=True, checksum_matches=True,
    )
    assert f.verdict is QCVerdict.PASS


def test_output_thieu_audio_la_fail():
    f = check_output_playable(
        duration_ms=7000, expected_duration_ms=7000,
        has_audio=False, has_video=True, checksum_matches=True,
    )
    assert f.verdict is QCVerdict.FAIL


def test_output_checksum_sai_la_fail():
    f = check_output_playable(
        duration_ms=7000, expected_duration_ms=7000,
        has_audio=True, has_video=True, checksum_matches=False,
    )
    assert f.verdict is QCVerdict.FAIL


def test_output_lech_thoi_luong_qua_xa_la_fail():
    f = check_output_playable(
        duration_ms=3000, expected_duration_ms=7000,
        has_audio=True, has_video=True, checksum_matches=True,
    )
    assert f.verdict is QCVerdict.FAIL


def test_loudness_gan_target_la_pass():
    assert check_loudness(-14.5, target_lufs=-14.0).verdict is QCVerdict.PASS


def test_loudness_lech_nhe_la_warn():
    f = check_loudness(-20.0, target_lufs=-14.0, tolerance_db=3.0)
    assert f.verdict is QCVerdict.WARN


def test_loudness_gan_nhu_im_lang_la_fail():
    f = check_loudness(-55.0, target_lufs=-14.0)
    assert f.verdict is QCVerdict.FAIL
    assert "lỗi trộn" in f.message


def test_khong_clipping_la_pass():
    assert check_no_clipping(-2.0).verdict is QCVerdict.PASS


def test_vuot_tran_an_toan_la_warn():
    f = check_no_clipping(-0.5, ceiling_db=-1.0)
    assert f.verdict is QCVerdict.WARN


def test_clipping_that_la_fail():
    f = check_no_clipping(0.5)
    assert f.verdict is QCVerdict.FAIL


def test_nen_con_nguyen_la_pass():
    assert check_background_retained(-30.0).verdict is QCVerdict.PASS


def test_nen_mat_la_fail():
    f = check_background_retained(-60.0, floor_db=-50.0)
    assert f.verdict is QCVerdict.FAIL
    assert "mất" in f.message


# --- tổng hợp verdict --------------------------------------------------------

def test_tong_hop_toan_pass_la_pass():
    findings = [check_cumulative_drift(100, max_drift_ms=300)]
    assert overall_verdict(findings) is QCVerdict.PASS


def test_tong_hop_co_warn_khong_fail_la_warn():
    findings = [
        check_cumulative_drift(100, max_drift_ms=300),
        check_cue_cps([20.0], cps_max=17.0),
    ]
    assert overall_verdict(findings) is QCVerdict.WARN


def test_tong_hop_co_fail_thi_luon_fail_du_con_lai_pass():
    findings = [
        check_cumulative_drift(100, max_drift_ms=300),
        check_cue_overlap([(0, 1000), (900, 2000)]),
    ]
    assert overall_verdict(findings) is QCVerdict.FAIL


def test_tong_hop_rong_la_pass():
    assert overall_verdict([]) is QCVerdict.PASS
