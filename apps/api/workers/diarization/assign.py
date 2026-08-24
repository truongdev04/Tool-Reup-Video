"""Gán speaker cho từng STT segment từ kết quả diarization — docs §6.5.

Module thuần: không I/O, không phụ thuộc `pyannote.audio` — nhận số đã đo (các
lượt nói từ diarization) và số cần gán (khung thời gian của từng stt_segment),
trả nhãn speaker theo overlap lớn nhất. Tách khỏi
`services/diarization_pyannote.py` theo đúng mẫu "logic thuần tách khỏi I/O"
của dự án (coding-style.md) — test được đầy đủ mà không cần chạy model thật.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiarizationTurn:
    """Một lượt nói do pyannote nhận diện — [start_ms, end_ms) thuộc về một speaker."""

    start_ms: int
    end_ms: int
    speaker: str


@dataclass(frozen=True)
class SegmentSpan:
    """Khung thời gian của một stt_segment cần gán speaker."""

    idx: int
    start_ms: int
    end_ms: int


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def assign_speakers(
    segments: list[SegmentSpan], turns: list[DiarizationTurn]
) -> dict[int, str]:
    """Gán mỗi segment nhãn speaker có tổng thời lượng chồng lấn LỚN NHẤT.

    stt_segment cắt theo khoảng lặng và lượt nói diarization cắt theo giọng
    hiếm khi khớp y hệt ranh giới — một segment có thể chồng lấn nhiều lượt
    nói (kể cả khác speaker, do lỗi model hoặc hai người nói chồng tiếng nhau).
    Chọn overlap lớn nhất thay vì lượt nói đầu tiên/gần điểm bắt đầu nhất để
    chống nhiễu đó.

    Segment không chồng lấn lượt nói nào (vd. rơi đúng vào khoảng lặng giữa
    hai lượt) thì KHÔNG có mặt trong dict trả về — caller giữ nguyên
    `speaker_id=None`. `segment_planner` đã coi `speaker=None` là "không đổi
    speaker" từ trước khi stage diarize tồn tại, nên không cần bịa giá trị mặc định.
    """
    result: dict[int, str] = {}
    for seg in segments:
        best_speaker: str | None = None
        best_overlap = 0
        for turn in turns:
            ov = _overlap_ms(seg.start_ms, seg.end_ms, turn.start_ms, turn.end_ms)
            if ov > best_overlap:
                best_overlap = ov
                best_speaker = turn.speaker
        if best_speaker is not None:
            result[seg.idx] = best_speaker
    return result


def total_speech_ms(turns: list[DiarizationTurn]) -> dict[str, int]:
    """Tổng thời lượng nói theo speaker — điền `Speaker.total_speech_ms`."""
    totals: dict[str, int] = {}
    for turn in turns:
        totals[turn.speaker] = totals.get(turn.speaker, 0) + max(0, turn.end_ms - turn.start_ms)
    return totals
