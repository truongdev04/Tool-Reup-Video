"""Logic gộp/tách segment — docs §5, §6.6.

Module thuần, không gọi API, không chạm DB — nên test được đầy đủ và rẻ.
Đây là nơi quyết định chất lượng của mọi bước sau: gộp sai thì LLM mất ngữ cảnh
và dịch sai; tách sai thì subtitle chạy quá nhanh hoặc giọng đọc bị cụt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.presets import LocalePreset

#: Trần ký tự cho một đơn vị dịch. Dài hơn thì LLM có xu hướng tóm tắt thay vì
#: dịch, và budget độ dài (§7.2) mất tác dụng vì sai số dồn quá lớn.
MAX_UNIT_CHARS = 250

#: Khoảng lặng đủ dài để coi là ranh giới câu, kể cả khi thiếu dấu chấm câu.
#: STT thường bỏ dấu câu ở cuối đoạn nên không thể chỉ dựa vào dấu.
SILENCE_BREAK_MS = 700


@dataclass
class RawSegment:
    """Một đoạn thô từ STT (tầng 1) — cắt theo khoảng lặng, hay cắt giữa câu."""

    idx: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    words: list[dict] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass
class PlannedUnit:
    """Một đơn vị dịch (tầng 2) — câu/ý trọn vẹn, gộp từ nhiều RawSegment."""

    idx: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None
    source_segment_idxs: list[int]
    char_budget: int = 0
    needs_transcreation: bool = False

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def _ends_sentence(text: str, enders: tuple[str, ...]) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in enders


def merge_to_units(
    segments: list[RawSegment],
    *,
    source_preset: LocalePreset,
    max_chars: int = MAX_UNIT_CHARS,
    silence_break_ms: int = SILENCE_BREAK_MS,
) -> list[PlannedUnit]:
    """Tầng 1 → tầng 2: gộp STT segment thành đơn vị dịch trọn nghĩa (§5).

    Cắt đơn vị khi gặp một trong bốn điều kiện:
      1. Kết thúc câu (dấu câu của ngôn ngữ nguồn)
      2. Khoảng lặng dài — STT hay bỏ dấu câu nên không thể chỉ dựa vào dấu
      3. Đổi người nói — không bao giờ gộp lời hai người vào một đơn vị dịch
      4. Chạm trần ký tự
    """
    units: list[PlannedUnit] = []
    buffer: list[RawSegment] = []

    def flush() -> None:
        if not buffer:
            return
        units.append(
            PlannedUnit(
                idx=len(units),
                start_ms=buffer[0].start_ms,
                end_ms=buffer[-1].end_ms,
                text=" ".join(s.text.strip() for s in buffer if s.text.strip()),
                speaker=buffer[0].speaker,
                source_segment_idxs=[s.idx for s in buffer],
            )
        )
        buffer.clear()

    for i, seg in enumerate(sorted(segments, key=lambda s: s.start_ms)):
        prev = buffer[-1] if buffer else None

        # Đổi speaker: chốt đơn vị đang dở TRƯỚC khi nhận segment mới.
        if prev is not None and seg.speaker != prev.speaker:
            flush()
            prev = None

        # Khoảng lặng dài giữa segment trước và segment này.
        if prev is not None and (seg.start_ms - prev.end_ms) >= silence_break_ms:
            flush()
            prev = None

        pending_chars = sum(len(s.text) + 1 for s in buffer) + len(seg.text)
        if prev is not None and pending_chars > max_chars:
            flush()

        buffer.append(seg)

        if _ends_sentence(seg.text, source_preset.sentence_enders):
            flush()
            continue

        # Segment cuối cùng: luôn chốt để không bỏ sót nội dung.
        if i == len(segments) - 1:
            flush()

    flush()
    return units


def assign_budgets(
    units: list[PlannedUnit],
    *,
    target_preset: LocalePreset,
) -> list[PlannedUnit]:
    """Gán char_budget cho từng đơn vị — chiến lược fit rẻ nhất (§7.2 #1).

    Budget tính từ thời lượng khung hình gốc và tốc độ đọc của ngôn ngữ ĐÍCH,
    nên bản tiếng Nhật tự nhiên được budget ký tự nhỏ hơn bản tiếng Tây Ban Nha
    cho cùng một đoạn.
    """
    for unit in units:
        unit.char_budget = target_preset.char_budget_for(unit.duration_ms)
    return units


def flag_transcreation(
    units: list[PlannedUnit],
    *,
    hook_window_ms: int = 3000,
    cta_window_ms: int = 4000,
) -> list[PlannedUnit]:
    """Đánh dấu hook và CTA cần dịch thoáng thay vì dịch sát (§6.7).

    Dịch sát nghĩa thường làm hỏng câu mở đầu và lời kêu gọi hành động — đây là
    hai chỗ quyết định tỉ lệ giữ chân người xem.
    """
    if not units:
        return units

    end_of_video = max(u.end_ms for u in units)
    for unit in units:
        is_hook = unit.start_ms < hook_window_ms
        is_cta = unit.end_ms > end_of_video - cta_window_ms
        unit.needs_transcreation = is_hook or is_cta
    return units


def plan(
    segments: list[RawSegment],
    *,
    source_preset: LocalePreset,
    target_preset: LocalePreset,
) -> list[PlannedUnit]:
    """Chạy cả ba bước: gộp → gán budget → đánh dấu transcreation."""
    units = merge_to_units(segments, source_preset=source_preset)
    units = assign_budgets(units, target_preset=target_preset)
    return flag_transcreation(units)
