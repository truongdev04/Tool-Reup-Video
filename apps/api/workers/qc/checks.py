"""Luật quyết định QC — docs §15.

Module thuần: nhận số liệu đã đo, trả về verdict. Việc ĐO (gọi ffmpeg/ffprobe,
đọc DB) nằm ở `stage.py` — tách riêng để test được toàn bộ luật mà không cần
video/audio thật.

Đây là nơi biến checklist §15 thành dữ liệu kiểm tra được, thay vì chỉ là danh
sách nhắc nhở trong tài liệu.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.types import QCVerdict


@dataclass(frozen=True)
class QCFinding:
    check: str
    verdict: QCVerdict
    message: str


def _finding(check: str, verdict: QCVerdict, message: str) -> QCFinding:
    return QCFinding(check=check, verdict=verdict, message=message)


def check_cumulative_drift(cumulative_drift_ms: int, *, max_drift_ms: int) -> QCFinding:
    """Chỉ số QC quan trọng nhất của hệ thống (§7, §15, DoD §21)."""
    if abs(cumulative_drift_ms) <= max_drift_ms:
        return _finding("drift", QCVerdict.PASS, f"drift cuối {cumulative_drift_ms}ms")
    return _finding(
        "drift", QCVerdict.FAIL,
        f"drift cuối {cumulative_drift_ms}ms vượt ngân sách {max_drift_ms}ms — "
        f"audio đã trôi khỏi hình",
    )


def check_forced_alignment_used(cue_count: int, all_from_forced_alignment: bool) -> QCFinding:
    """Nguyên tắc bất biến §2.9/§8.3: subtitle phải đến từ audio sẽ phát."""
    if cue_count == 0:
        return _finding("forced_alignment", QCVerdict.FAIL, "không có cue nào — subtitle rỗng")
    if not all_from_forced_alignment:
        return _finding(
            "forced_alignment", QCVerdict.FAIL,
            "có cue KHÔNG đến từ forced_align — vi phạm nguyên tắc bất biến §8.3",
        )
    return _finding("forced_alignment", QCVerdict.PASS, f"{cue_count} cue, đều từ forced_align")


def check_cue_overlap(cues: list[tuple[int, int]]) -> QCFinding:
    """Không cue nào chồng lấn — §15."""
    ordered = sorted(cues)
    for (_, end), (next_start, _) in zip(ordered, ordered[1:]):
        if next_start < end:
            return _finding(
                "cue_overlap", QCVerdict.FAIL,
                f"cue chồng lấn: kết thúc {end}ms nhưng cue sau bắt đầu {next_start}ms",
            )
    return _finding("cue_overlap", QCVerdict.PASS, f"{len(ordered)} cue không chồng lấn")


def check_cue_cps(cps_values: list[float], *, cps_max: float, hard_ceiling_ratio: float = 1.5) -> QCFinding:
    """CPS theo locale — §15.

    Cue hơi vượt cps_max được CHẤP NHẬN có chủ ý khi unit quá ngắn để tách
    (§6.11 — xem workers/subtitle/splitter.py), nên chỉ FAIL khi vượt xa; vượt
    nhẹ thì WARN để biết mà không chặn.
    """
    severe = [c for c in cps_values if c > cps_max * hard_ceiling_ratio]
    mild = [c for c in cps_values if cps_max < c <= cps_max * hard_ceiling_ratio]
    if severe:
        return _finding(
            "cue_cps", QCVerdict.FAIL,
            f"{len(severe)} cue vượt xa cps_max ({cps_max}) — quá {hard_ceiling_ratio}x",
        )
    if mild:
        return _finding(
            "cue_cps", QCVerdict.WARN,
            f"{len(mild)} cue vượt nhẹ cps_max ({cps_max}) — chấp nhận vì unit quá ngắn để tách",
        )
    return _finding("cue_cps", QCVerdict.PASS, "mọi cue trong ngưỡng CPS")


def check_tempo_bounds(tempo_ratios: list[float], *, tempo_min: float, tempo_max: float) -> QCFinding:
    """Phòng thủ: không segment nào vượt ngưỡng tempo an toàn (§7.2, DoD §21).

    Đáng lẽ không thể xảy ra vì fitter đã chặn — FAIL ở đây nghĩa là có bug
    thật ở duration_fit hoặc tts, không phải điều chỉnh bình thường.
    """
    bad = [r for r in tempo_ratios if not (tempo_min <= r <= tempo_max)]
    if bad:
        return _finding(
            "tempo_bounds", QCVerdict.FAIL,
            f"{len(bad)} chunk có tempo ngoài [{tempo_min}, {tempo_max}]: {bad} — "
            f"bug ở duration_fit/tts, fitter lẽ ra phải chặn",
        )
    return _finding("tempo_bounds", QCVerdict.PASS, "mọi tempo trong ngưỡng an toàn")


def check_translation_completeness(units_total: int, translations_present: int) -> QCFinding:
    """Không thiếu segment — §15. Phòng thủ: translate stage đã raise cứng khi
    thiếu, FAIL ở đây nghĩa là dữ liệu bị xoá/hỏng sau đó."""
    if units_total == 0:
        return _finding("translation_complete", QCVerdict.FAIL, "không có translation_unit nào")
    if translations_present < units_total:
        return _finding(
            "translation_complete", QCVerdict.FAIL,
            f"chỉ {translations_present}/{units_total} đơn vị có bản dịch — "
            f"video sẽ câm một đoạn",
        )
    return _finding("translation_complete", QCVerdict.PASS, f"đủ {units_total} đơn vị")


def check_output_playable(
    *,
    duration_ms: int,
    expected_duration_ms: int,
    has_audio: bool,
    has_video: bool,
    checksum_matches: bool,
    tolerance_ms: int = 1000,
) -> QCFinding:
    """File mở được, đúng thời lượng, checksum khớp — §15."""
    if not has_video:
        return _finding("output_playable", QCVerdict.FAIL, "output không có video stream")
    if not has_audio:
        return _finding("output_playable", QCVerdict.FAIL, "output không có audio stream")
    if not checksum_matches:
        return _finding("output_playable", QCVerdict.FAIL, "checksum không khớp file đã lưu")
    if abs(duration_ms - expected_duration_ms) > tolerance_ms:
        return _finding(
            "output_playable", QCVerdict.FAIL,
            f"thời lượng {duration_ms}ms lệch quá xa so với nguồn {expected_duration_ms}ms",
        )
    return _finding("output_playable", QCVerdict.PASS, f"mở được, {duration_ms}ms, checksum khớp")


def check_loudness(measured_lufs: float, *, target_lufs: float, tolerance_db: float = 3.0) -> QCFinding:
    """Loudness hợp lý — §9, §15."""
    if measured_lufs < -40.0:
        return _finding(
            "loudness", QCVerdict.FAIL,
            f"đo được {measured_lufs} LUFS — gần như im lặng, có khả năng lỗi trộn audio",
        )
    if abs(measured_lufs - target_lufs) > tolerance_db:
        return _finding(
            "loudness", QCVerdict.WARN,
            f"đo được {measured_lufs} LUFS, lệch quá {tolerance_db}dB so với mục tiêu {target_lufs}",
        )
    return _finding("loudness", QCVerdict.PASS, f"{measured_lufs} LUFS, gần mục tiêu {target_lufs}")


def check_no_clipping(true_peak_db: float, *, ceiling_db: float = -1.0) -> QCFinding:
    """Không clipping — §15."""
    if true_peak_db > 0.0:
        return _finding("clipping", QCVerdict.FAIL, f"true peak {true_peak_db}dBTP — có clipping thật")
    if true_peak_db > ceiling_db:
        return _finding(
            "clipping", QCVerdict.WARN,
            f"true peak {true_peak_db}dBTP vượt trần an toàn {ceiling_db}dBTP",
        )
    return _finding("clipping", QCVerdict.PASS, f"true peak {true_peak_db}dBTP, an toàn")


def check_background_retained(gap_rms_db: float, *, floor_db: float = -50.0) -> QCFinding:
    """Nhạc nền/tiếng động gốc còn nguyên — §9, §15.

    Đo năng lượng tại một khoảng KHÔNG có lời thoại (giữa hai unit). Gần như
    im lặng ở đó nghĩa là track nền đã bị mất khi tái dựng audio (§9: track
    cuối phải là TTS + background gốc, không phải thay thế).
    """
    if gap_rms_db < floor_db:
        return _finding(
            "background_retained", QCVerdict.FAIL,
            f"năng lượng nền tại khoảng lặng chỉ {gap_rms_db}dBFS — nhạc nền có "
            f"thể đã bị mất khi trộn (§9)",
        )
    return _finding("background_retained", QCVerdict.PASS, f"nền còn nguyên ({gap_rms_db}dBFS)")


def check_font_coverage(missing_chars: list[str]) -> QCFinding:
    """Mọi ký tự trong subtitle phải có glyph trong font chain đã khai báo
    (§13.2, §14, §15) — FAIL chứ không WARN: glyph thiếu là ô vuông nhìn thấy
    ngay trên hình, không phải sai lệch nhỏ có thể chấp nhận như `cue_cps`
    (xem lý do `cue_cps` chỉ WARN ở `check_cue_cps`, đây KHÔNG cùng tình huống
    — thiếu glyph không có "chấp nhận được" nào)."""
    if missing_chars:
        preview = "".join(sorted(set(missing_chars))[:10])
        return _finding(
            "font_coverage", QCVerdict.FAIL,
            f"{len(set(missing_chars))} ký tự không có glyph trong font đã khai "
            f"(vd: {preview}) — sẽ hiện ô vuông trên hình",
        )
    return _finding("font_coverage", QCVerdict.PASS, "mọi ký tự đều có glyph")


def overall_verdict(findings: list[QCFinding]) -> QCVerdict:
    """Tổng hợp: 1 FAIL -> FAIL cả job; không FAIL nhưng có WARN -> WARN;
    còn lại PASS. Chỉ publish khi = PASS (§15)."""
    if any(f.verdict == QCVerdict.FAIL for f in findings):
        return QCVerdict.FAIL
    if any(f.verdict == QCVerdict.WARN for f in findings):
        return QCVerdict.WARN
    return QCVerdict.PASS
