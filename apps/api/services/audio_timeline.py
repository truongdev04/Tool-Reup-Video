"""Ghép các chunk TTS vào đúng vị trí tuyệt đối trên trục thời gian video — docs §9.

Mỗi chunk được đặt tại `unit.start_ms` của chính nó trong video GỐC, không nối
đuôi nhau — nhờ vậy khoảng lặng giữa các lời thoại và các mốc hình ảnh (chuyển
cảnh, nhạc nền) vẫn đúng chỗ. Track này là phần "giọng nói"; trộn với
`background.wav` (giữ nguyên từ Demucs) diễn ra ở stage `render` (§9).
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Chuẩn nội bộ cho mọi audio trung gian trong pipeline — khớp với
#: extract_audio() và TTSConfig.sample_rate mặc định.
SAMPLE_RATE = 44100


@dataclass(frozen=True)
class PlacedChunk:
    start_ms: int
    path: Path


@dataclass
class AssemblyResult:
    path: Path
    total_duration_ms: int
    #: (unit_start_ms, overlap_ms) — chunk tràn vào chunk kế tiếp. Không chặn
    #: pipeline (chồng lấn vẫn cộng dồn được), nhưng đáng để QC xem lại (§15).
    overlaps: list[tuple[int, int]]


def _read_pcm16_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as fh:
        if fh.getsampwidth() != 2:
            raise ValueError(f"{path} không phải PCM 16-bit: {fh.getsampwidth()} byte/mẫu")
        frames = fh.readframes(fh.getnframes())
        data = np.frombuffer(frames, dtype=np.int16)
        if fh.getnchannels() > 1:
            data = data.reshape(-1, fh.getnchannels()).mean(axis=1).astype(np.int16)
        if fh.getframerate() != SAMPLE_RATE:
            raise ValueError(
                f"{path} có sample rate {fh.getframerate()}, kỳ vọng {SAMPLE_RATE}. "
                f"Mọi audio trung gian phải cùng sample rate trước khi ghép."
            )
        return data.astype(np.int32)  # int32 để cộng dồn không tràn số


def assemble(
    chunks: list[PlacedChunk],
    total_duration_ms: int,
    out_path: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> AssemblyResult:
    """Dựng một track WAV dài `total_duration_ms`, im lặng, rồi ghi đè từng
    chunk vào đúng vị trí tuyệt đối `chunk.start_ms`.

    Cộng dồn (không thay thế) khi hai chunk chồng lấn — hiếm khi xảy ra vì
    Duration Fitting (§7) đã cố giữ mỗi chunk trong khung của nó, nhưng chiến
    lược BORROW_SILENCE có thể lấn nhẹ vào khoảng trống sau. Ghi nhận lại để
    QC xem xét, không âm thầm bỏ qua.
    """
    total_samples = max(1, round(total_duration_ms / 1000 * sample_rate))
    buffer = np.zeros(total_samples, dtype=np.int32)
    occupied_until = 0  # mẫu cuối cùng đã có audio, để phát hiện chồng lấn
    overlaps: list[tuple[int, int]] = []

    for chunk in sorted(chunks, key=lambda c: c.start_ms):
        samples = _read_pcm16_mono(chunk.path)
        start_sample = round(chunk.start_ms / 1000 * sample_rate)
        end_sample = min(total_samples, start_sample + len(samples))
        if end_sample <= start_sample:
            continue

        if start_sample < occupied_until:
            overlap_ms = round((occupied_until - start_sample) / sample_rate * 1000)
            overlaps.append((chunk.start_ms, overlap_ms))

        buffer[start_sample:end_sample] += samples[: end_sample - start_sample]
        occupied_until = max(occupied_until, end_sample)

    # Giới hạn về lại khoảng int16 hợp lệ — cộng dồn ở overlap có thể vượt biên.
    clipped = np.clip(buffer, -32768, 32767).astype(np.int16)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(clipped.tobytes())

    return AssemblyResult(path=out_path, total_duration_ms=total_duration_ms, overlaps=overlaps)
