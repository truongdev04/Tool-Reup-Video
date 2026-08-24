"""Khôi phục timestamp cấp ký tự trên audio TTS đã sinh — docs §8.

**Đây KHÔNG phải forced alignment đúng nghĩa** (WhisperX/MFA align văn bản đã
biết với audio qua acoustic model CTC theo từng ngôn ngữ). Cách này dùng chính
STT (mlx-whisper) chạy lại trên audio mới để lấy CẤU TRÚC THỜI GIAN — ranh giới
đoạn tại các khoảng lặng tự nhiên — làm mốc thật. **Không dùng phần text nhận
dạng được**: giọng TTS dễ khiến STT nhận nhầm chính tả, nên nội dung hiển thị
luôn là bản dịch gốc đáng tin cậy, chỉ có THỜI GIAN là lấy từ STT.

Lý do không dùng WhisperX/MFA: cả hai cần model CTC theo từng ngôn ngữ
(wav2vec2). Các bộ có sẵn phủ tốt tiếng Anh/Âu nhưng rất yếu hoặc không có cho
tiếng Nhật, tiếng Việt, tiếng Ả Rập — đúng các locale mục tiêu của tool này
(§23 #4). Cách neo-theo-đoạn dưới đây hoạt động bất kể ngôn ngữ vì chỉ cần
BIÊN THỜI GIAN của STT, không cần model riêng cho từng ngôn ngữ.

Đây là xấp xỉ, không phải alignment chính xác cấp phoneme — trong mỗi đoạn,
ký tự được rải ĐỀU theo thời gian (giả định tốc độ đọc không đổi trong đoạn).
Ghi nhận như một khoản nợ kỹ thuật: nâng cấp lên WhisperX cho các locale có
model CTC tốt là việc hợp lý ở Phase 2+ nếu cần độ chính xác cao hơn (vd. cho
karaoke-highlight hoặc lip-sync).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechSpan:
    """Một đoạn có tiếng nói, biên lấy từ STT chạy trên chính audio TTS."""

    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def char_time_map(
    text: str,
    spans: list[SpeechSpan],
    total_duration_ms: int,
) -> list[int]:
    """Trả về `len(text) + 1` mốc thời gian (ms) — biên giữa các ký tự.

    Ký tự thứ `i` (0-based) chiếm khoảng `[map[i], map[i+1])`. Cách dùng:
    thời lượng của `text[a:b]` là `map[b] - map[a]`.

    Ký tự CHỈ được rải vào các `spans` có tiếng nói — khoảng lặng giữa các
    đoạn bị bỏ qua khi rải (không có ký tự nào "nằm trong" khoảng lặng), nhưng
    vẫn được giữ nguyên vị trí thật trên trục thời gian khi quy đổi ngược.

    Không có span nào (STT không nhận ra tiếng nói) thì rải đều trên toàn bộ
    `total_duration_ms` — an toàn hơn là báo lỗi, vì cùng lắm chỉ kém chính xác
    chứ không chặn cả pipeline.
    """
    n = len(text)
    if n == 0:
        return [0]

    usable = [s for s in spans if s.duration_ms > 0]
    if not usable:
        usable = [SpeechSpan(0, max(1, total_duration_ms))]

    total_voiced = sum(s.duration_ms for s in usable)
    cumulative_before: list[int] = []
    acc = 0
    for s in usable:
        cumulative_before.append(acc)
        acc += s.duration_ms

    boundaries: list[int] = []
    for i in range(n + 1):
        virtual_t = i / n * total_voiced
        # Tìm span chứa virtual_t (đoạn cuối nhận luôn phần dư do làm tròn).
        idx = 0
        for k in range(len(usable)):
            if virtual_t < cumulative_before[k] + usable[k].duration_ms or k == len(usable) - 1:
                idx = k
                break
        local_t = virtual_t - cumulative_before[idx]
        boundaries.append(usable[idx].start_ms + round(local_t))

    return boundaries


def span_duration_ms(boundaries: list[int], start_char: int, end_char: int) -> int:
    """Thời lượng ước tính của `text[start_char:end_char]`, từ `char_time_map`."""
    return max(0, boundaries[end_char] - boundaries[start_char])
