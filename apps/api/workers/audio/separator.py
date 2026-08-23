"""Tách vocals / background bằng Demucs — docs §6.3, §9.

Giữ lại track `background` là bắt buộc: track cuối phải được TÁI DỰNG
(`TTS + background gốc`), không phải thay thế. Thay nguyên track audio bằng TTS
là mất sạch nhạc nền, tiếng động và không khí của video gốc (§9).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import torch

from services.ffmpeg import run_ffmpeg

log = logging.getLogger("vla.separate")

#: htdemucs là model mặc định của Demucs 4 — 4 stem: drums, bass, other, vocals.
DEFAULT_MODEL = "htdemucs"

#: Ba stem không phải giọng nói, gộp lại thành `background`.
_BACKGROUND_STEMS = ("drums", "bass", "other")


@dataclass(frozen=True)
class SeparationResult:
    vocals_path: Path
    background_path: Path
    model: str
    device: str
    sample_rate: int


def pick_device() -> str:
    """MPS trên Apple Silicon, CUDA nếu có, còn lại CPU.

    Demucs chạy MPS nhanh hơn CPU đáng kể trên M-series, nhưng một số phép toán
    vẫn rơi về CPU nên đừng kỳ vọng tốc độ như CUDA.
    """
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def extract_audio(video_path: Path, out_path: Path, *, sample_rate: int = 44100) -> Path:
    """Rút audio khỏi video thành WAV để Demucs xử lý."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(video_path),
        "-vn", "-ac", "2", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le", str(out_path),
    ])
    return out_path


def separate(
    audio_path: Path,
    out_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
    device: str | None = None,
) -> SeparationResult:
    """Tách thành `vocals.wav` và `background.wav`.

    Idempotent: đã có sẵn cả hai file thì không chạy lại — Demucs là bước đắt
    nhất của pipeline nên đây là chỗ cache có giá trị nhất (§16).
    """
    from demucs.api import Separator, save_audio

    out_dir.mkdir(parents=True, exist_ok=True)
    vocals_path = out_dir / "vocals.wav"
    background_path = out_dir / "background.wav"

    device = device or pick_device()

    if vocals_path.exists() and background_path.exists():
        log.info("bỏ qua separation, đã có sẵn: %s", out_dir)
        separator = None
        sample_rate = 44100
    else:
        separator = Separator(model=model, device=device)
        _origin, stems = separator.separate_audio_file(audio_path)
        sample_rate = separator.samplerate

        save_audio(stems["vocals"], str(vocals_path), samplerate=sample_rate)

        # Gộp 3 stem còn lại thành một track nền duy nhất.
        background = sum(stems[name] for name in _BACKGROUND_STEMS)
        save_audio(background, str(background_path), samplerate=sample_rate)

    return SeparationResult(
        vocals_path=vocals_path,
        background_path=background_path,
        model=model,
        device=device,
        sample_rate=sample_rate,
    )
