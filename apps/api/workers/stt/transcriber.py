"""Speech-to-Text bằng mlx-whisper — docs §6.4, §13.1.

Chọn MLX vì chạy Metal trên Apple Silicon; `faster-whisper` (CTranslate2) chỉ
chạy CPU trên Mac nên chậm hơn đáng kể (§13.1).

Word-level timestamp là BẮT BUỘC, không phải tuỳ chọn: Duration Fitting (§7) cần
nó để tính khoảng lặng mượn được, Subtitle (§8) cần nó để cắt cue. Thiếu nó thì
hai stage đó không có căn cứ nào để làm việc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("vla.stt")

#: Model mặc định. large-v3-turbo cân bằng tốt nhất: gần large-v3 về chất lượng
#: nhưng nhanh hơn nhiều lần. STT sai thì mọi bước sau sai theo, nên không nên
#: tiết kiệm ở đây khi chạy thật.
DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"

#: Model nhẹ cho vòng lặp phát triển — DoD §21 yêu cầu clip 10s chạy dưới 2 phút.
DEV_MODEL = "mlx-community/whisper-base-mlx"


def resolve_model_for_env() -> str:
    """Model nhẹ cho dev, model đầy đủ cho chạy thật.

    Cấu hình qua env chứ không hard-code (§2.2). DoD §21 yêu cầu clip 10s chạy
    hết pipeline dưới 2 phút — large-v3-turbo tải model lần đầu mất lâu hơn thế.
    Dùng chung giữa stage `stt` và `forced_align` — cả hai đều gọi Whisper.
    """
    import os

    return os.environ.get("VLA_WHISPER_MODEL") or (
        DEV_MODEL if os.environ.get("VLA_DEV_FAST") else DEFAULT_MODEL
    )


@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int


@dataclass
class Segment:
    idx: int
    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)

    def to_json_words(self) -> list[dict]:
        return [{"word": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in self.words]


@dataclass
class TranscriptResult:
    language: str
    segments: list[Segment]
    model: str
    full_text: str

    @property
    def has_word_timestamps(self) -> bool:
        return any(s.words for s in self.segments)

    @property
    def duration_ms(self) -> int:
        return max((s.end_ms for s in self.segments), default=0)


def _ms(seconds: float | None) -> int:
    return int(round((seconds or 0.0) * 1000))


def transcribe(
    audio_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
) -> TranscriptResult:
    """Nhận dạng lời nói, trả transcript có timestamp cấp từ.

    `language=None` để Whisper tự nhận diện. Truyền locale nguồn khi đã biết thì
    kết quả ổn định hơn và nhanh hơn (bỏ được bước detect).
    """
    import mlx_whisper

    raw = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        language=language,
        word_timestamps=True,  # bắt buộc — xem docstring module
        condition_on_previous_text=False,  # tránh lặp/ảo giác khi có khoảng lặng dài
    )

    segments: list[Segment] = []
    for i, seg in enumerate(raw.get("segments", [])):
        words = [
            Word(
                text=w.get("word", "").strip(),
                start_ms=_ms(w.get("start")),
                end_ms=_ms(w.get("end")),
            )
            for w in seg.get("words", []) or []
            if w.get("word", "").strip()
        ]
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            Segment(
                idx=len(segments),
                start_ms=_ms(seg.get("start")),
                end_ms=_ms(seg.get("end")),
                text=text,
                words=words,
            )
        )

    result = TranscriptResult(
        language=raw.get("language") or language or "unknown",
        segments=segments,
        model=model,
        full_text=(raw.get("text") or "").strip(),
    )

    if segments and not result.has_word_timestamps:
        raise RuntimeError(
            "Whisper không trả word-level timestamp. Duration Fitting (§7) và "
            "Subtitle (§8) đều phụ thuộc vào nó — không thể đi tiếp"
        )
    return result


def silence_gaps(segments: list[Segment]) -> list[int]:
    """Khoảng lặng (ms) NGAY SAU mỗi segment.

    Duration Fitting dùng số này cho chiến lược #2 "ăn vào khoảng lặng" (§7.2).
    Phần tử cuối luôn là 0: không biết sau segment cuối còn bao nhiêu, nên
    không cho phép mượn.
    """
    gaps: list[int] = []
    for i, seg in enumerate(segments):
        if i + 1 < len(segments):
            gaps.append(max(0, segments[i + 1].start_ms - seg.end_ms))
        else:
            gaps.append(0)
    return gaps
