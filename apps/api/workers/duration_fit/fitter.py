"""Thang chiến lược ép thời lượng — docs §7.

Đây là bài toán khó nhất của dubbing và là lỗ hổng lớn nhất của kế hoạch v2.
Cùng một câu, thời lượng đọc giữa các ngôn ngữ lệch nhau 15–35%; không ép khớp
thì audio trôi dần khỏi hình, lip-sync mất căn cứ và subtitle lệch theo.

Module thuần: nhận số liệu, trả quyết định. Việc gọi LLM/TTS/ffmpeg nằm ở stage.
Nhờ vậy toàn bộ luật ép thời lượng test được mà không tốn tiền API.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.types import FitStrategy

#: Sai số chấp nhận được cho một đơn vị: dưới ngưỡng này coi như đã khớp.
DEFAULT_TOLERANCE = 0.10


@dataclass(frozen=True)
class FitPolicy:
    """Ngưỡng lấy từ Settings/fitting preset — không hard-code (§2.2, §14)."""

    tempo_min: float = 0.92
    tempo_max: float = 1.08
    min_silence_keep_ms: int = 150
    tolerance: float = DEFAULT_TOLERANCE
    allow_video_stretch: bool = True
    max_translate_attempts: int = 2
    #: Co giãn hình quá ngưỡng này là NHÌN THẤY được trên màn hình. Vượt thì
    #: thà chuyển manual review còn hơn xuất ra video giật hoặc chạy chậm.
    max_video_stretch_ratio: float = 0.12
    #: Audio ngắn hơn khung thì chèn im lặng — vô hại. Nhưng im lặng dài quá
    #: nửa khung nghĩa là bản dịch bị hụt nội dung, cần người xem lại.
    max_pad_ratio: float = 0.5
    #: Trần drift tích luỹ cho cả video (§15, DoD §21). Quyết định của từng đơn
    #: vị phải soi vào con số này, không được xét đơn vị đó một cách độc lập.
    max_cumulative_drift_ms: int = 300


@dataclass(frozen=True)
class FitInput:
    target_duration_ms: int
    actual_duration_ms: int
    #: Khoảng lặng còn trống ngay sau đơn vị này, đã trừ phần phải chừa lại.
    available_silence_ms: int = 0
    #: Có mặt người trong khung hình không — cấm co giãn hình nếu có (§7.2).
    has_face: bool = False
    translate_attempts: int = 0
    #: Drift đã dồn từ các đơn vị TRƯỚC đó. Không có tham số này thì mỗi đơn vị
    #: đều "nằm trong sai số" nhưng cộng lại vẫn vỡ ngưỡng — xem
    #: test_drift_tich_luy_bat_loi_ma_tung_don_vi_bo_sot.
    cumulative_drift_ms: int = 0


@dataclass(frozen=True)
class FitDecision:
    strategy: FitStrategy
    #: Hệ số atempo cần áp (1.0 = không đổi).
    tempo_ratio: float = 1.0
    #: Số ms mượn từ khoảng lặng kế tiếp.
    borrow_silence_ms: int = 0
    #: Số ms cần co giãn phần hình.
    video_adjust_ms: int = 0
    #: Số ms im lặng chèn thêm vào cuối đơn vị khi audio đọc ngắn hơn khung.
    pad_silence_ms: int = 0
    #: Budget ký tự mới, khi cần dịch lại cho ngắn/dài hơn.
    retry_char_budget: int | None = None
    drift_ms: int = 0
    needs_manual_review: bool = False
    reason: str = ""


def _within(actual: int, target: int, tolerance: float) -> bool:
    if target <= 0:
        return actual == 0
    return abs(actual - target) / target <= tolerance


def decide(
    fit: FitInput,
    *,
    policy: FitPolicy,
    speech_rate_cps: float,
) -> FitDecision:
    """Chọn chiến lược ép thời lượng, theo đúng thứ tự ưu tiên của §7.2.

    Rẻ và ít hại nhất trước; chỉ leo lên bước sau khi bước trước không đủ:
      1. Dịch có ràng buộc  — chất lượng cao nhất, chi phí thấp nhất
      2. Ăn vào khoảng lặng — không đụng tới giọng đọc
      3. Chỉnh tempo        — bắt đầu nghe ra được, nên giới hạn ngưỡng chặt
      4. Co giãn hình       — phương án cuối, cấm khi có mặt người

    Không chiến lược nào đủ thì đánh dấu manual review, KHÔNG ép bừa.

    Quyết định luôn soi vào drift TÍCH LUỸ, không xét đơn vị này một cách độc
    lập: sai số 10% mỗi đơn vị nghe thì nhỏ, nhưng 8 đơn vị như vậy dồn lại đã
    vượt xa ngưỡng 300ms của DoD §21. Khi đã có drift từ trước, đơn vị này phải
    đọc bù ngược lại để kéo tổng về 0 — nên khung thời gian đích của nó là
    `target - cumulative_drift`, không phải `target`.
    """
    target, actual = fit.target_duration_ms, fit.actual_duration_ms
    raw_delta = actual - target
    projected = fit.cumulative_drift_ms + raw_delta

    # Khung thời gian thực sự phải nhắm tới: đã trừ phần drift cần kéo về.
    effective_target = max(1, target - fit.cumulative_drift_ms)

    # Bỏ qua chỉ khi đơn vị này lệch ít VÀ tổng vẫn nằm trong ngân sách.
    if _within(actual, target, policy.tolerance) and abs(projected) <= policy.max_cumulative_drift_ms:
        return FitDecision(
            strategy=FitStrategy.NONE, drift_ms=raw_delta,
            reason="lệch nhỏ và drift tích luỹ vẫn trong ngân sách",
        )

    #: Fit thành công = kéo tổng drift về 0, nên đóng góp của đơn vị này phải
    #: triệt tiêu phần đã dồn trước đó.
    settled_drift = -fit.cumulative_drift_ms
    delta = actual - effective_target

    # --- 0. Audio NGẮN hơn khung: chèn im lặng ------------------------------
    # Hai chiều lệch không đối xứng. Đọc dài hơn khung là vấn đề thật, phải nén.
    # Đọc ngắn hơn thì video cứ chạy tiếp và audio kết thúc sớm — chèn im lặng
    # là xong, không việc gì phải đụng tới tốc độ đọc hay co giãn hình.
    if delta < 0:
        pad = -delta
        if pad <= effective_target * policy.max_pad_ratio:
            return FitDecision(
                strategy=FitStrategy.PAD_SILENCE,
                pad_silence_ms=pad, drift_ms=settled_drift,
                reason=f"chèn {pad}ms im lặng — audio đọc ngắn hơn khung, không cần nén",
            )
        return FitDecision(
            strategy=FitStrategy.MANUAL_REVIEW,
            drift_ms=raw_delta, needs_manual_review=True,
            reason=(
                f"audio ngắn hơn khung {pad}ms (hơn {policy.max_pad_ratio:.0%} khung) — "
                f"bản dịch nhiều khả năng bị hụt nội dung"
            ),
        )

    # --- 1. Dịch lại có ràng buộc độ dài -------------------------------------
    if fit.translate_attempts < policy.max_translate_attempts:
        return FitDecision(
            strategy=FitStrategy.CONSTRAINED_TRANSLATION,
            retry_char_budget=max(1, round(effective_target / 1000 * speech_rate_cps)),
            drift_ms=raw_delta,
            reason=f"dịch lại lần {fit.translate_attempts + 1} với budget theo thời lượng đích",
        )

    # --- 2. Mượn khoảng lặng kế tiếp -----------------------------------------
    # Chỉ áp dụng khi đọc DÀI hơn khung hình: mượn im lặng phía sau để bù.
    borrowed = 0
    if delta > 0 and fit.available_silence_ms > 0:
        borrowed = min(delta, fit.available_silence_ms)
        if borrowed == delta:
            return FitDecision(
                strategy=FitStrategy.BORROW_SILENCE,
                borrow_silence_ms=borrowed, drift_ms=settled_drift,
                reason=f"mượn {borrowed}ms khoảng lặng, không phải đụng giọng đọc",
            )
        # Mượn được một phần — phần còn lại để tempo xử lý tiếp.

    # --- 3. Chỉnh tempo trong ngưỡng an toàn ---------------------------------
    # Sau khi đã mượn `borrowed` ms, khung cho phép là effective_target + borrowed.
    # tempo_ratio = actual / khung; >1 nghĩa là phải đọc nhanh lên.
    frame = effective_target + borrowed
    if frame > 0:
        ratio = round(actual / frame, 4)
        if policy.tempo_min <= ratio <= policy.tempo_max:
            return FitDecision(
                strategy=FitStrategy.TEMPO_ADJUST,
                tempo_ratio=ratio, borrow_silence_ms=borrowed, drift_ms=settled_drift,
                reason=f"atempo {ratio} nằm trong ngưỡng an toàn",
            )

    # --- 4. Co giãn hình (phương án cuối) ------------------------------------
    stretch_ms = actual - effective_target
    stretch_ratio = abs(stretch_ms) / effective_target if effective_target else 1.0
    if (
        policy.allow_video_stretch
        and not fit.has_face
        and stretch_ratio <= policy.max_video_stretch_ratio
    ):
        return FitDecision(
            strategy=FitStrategy.VIDEO_STRETCH,
            video_adjust_ms=stretch_ms, drift_ms=settled_drift,
            reason=f"co giãn hình {stretch_ratio:.1%} ở đoạn không có mặt người",
        )

    # --- Không ép được -------------------------------------------------------
    return FitDecision(
        strategy=FitStrategy.MANUAL_REVIEW,
        drift_ms=raw_delta,
        needs_manual_review=True,
        reason=(
            f"lệch {raw_delta}ms, vượt mọi ngưỡng an toàn"
            + (
                " và có mặt người nên không co giãn hình được"
                if fit.has_face
                else f" (co giãn hình cần {stretch_ratio:.0%}, "
                     f"trần {policy.max_video_stretch_ratio:.0%})"
            )
        ),
    )


def accumulate_drift(decisions: list[FitDecision]) -> list[int]:
    """Drift tích luỹ theo thứ tự đơn vị — chỉ số QC quan trọng nhất (§15).

    Nó bắt được loại lỗi mà mọi kiểm tra khác bỏ sót: từng đơn vị đều nằm trong
    sai số nhưng cộng dồn lại thì audio nói về cảnh đã trôi qua từ lâu.
    """
    total = 0
    out: list[int] = []
    for d in decisions:
        total += d.drift_ms
        out.append(total)
    return out
