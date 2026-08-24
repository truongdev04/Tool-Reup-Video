"""Trộn giọng + nhạc nền và loudnorm hai lượt — docs §9.

Gọi ffmpeg thật (không mock) — nhất quán với cách test_phase0.py xác minh khả
năng ffmpeg bằng lệnh thật thay vì giả lập.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from services.audio_mix import TARGET_I, loudnorm_two_pass, mix_voice_and_background
from services.ffmpeg import probe


def _write_wav(path: Path, duration_ms: int, freq: float, amplitude: float = 0.3) -> Path:
    sr = 44100
    t = np.linspace(0, duration_ms / 1000, round(duration_ms / 1000 * sr), endpoint=False)
    samples = (np.sin(2 * np.pi * freq * t) * amplitude * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1); fh.setsampwidth(2); fh.setframerate(sr)
        fh.writeframes(samples.tobytes())
    return path


def test_tron_giong_va_nen_ra_dung_do_dai(tmp_path):
    voice = _write_wav(tmp_path / "voice.wav", 2000, freq=440)
    bg = _write_wav(tmp_path / "bg.wav", 3000, freq=220)  # nền dài hơn giọng

    out = mix_voice_and_background(voice, bg, tmp_path / "mixed.wav")
    info = probe(out)
    # duration=first -> khớp độ dài GIỌNG, không phải nền (§9: giọng chiếm ưu thế)
    assert info.duration_ms == pytest.approx(2000, abs=50)


def test_khong_mat_nen_khi_tron(tmp_path):
    """Đảm bảo track nền THẬT SỰ được cộng vào, không bị bỏ qua."""
    voice = _write_wav(tmp_path / "voice.wav", 1000, freq=440, amplitude=0.0)  # giọng im lặng
    bg = _write_wav(tmp_path / "bg.wav", 1000, freq=220, amplitude=0.3)

    out = mix_voice_and_background(voice, bg, tmp_path / "mixed.wav")
    with wave.open(str(out), "rb") as fh:
        data = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)
    assert np.abs(data).mean() > 100, "giọng im lặng nhưng track ra vẫn phải có năng lượng từ nền"


def test_loudnorm_hai_luot_dua_ve_gan_target(tmp_path):
    # Biên độ thấp cố ý (rất êm) để chắc chắn cần chuẩn hoá lên đáng kể.
    quiet = _write_wav(tmp_path / "quiet.wav", 3000, freq=440, amplitude=0.02)
    out = loudnorm_two_pass(quiet, tmp_path / "normalized.wav")

    assert out.exists()
    # Đo lại bằng chính hàm đo lượt 1 để xác nhận đã tiệm cận target.
    from services.audio_mix import measure_loudnorm
    measured = measure_loudnorm(out)
    assert abs(float(measured["input_i"]) - TARGET_I) < 3.0, (
        f"sau chuẩn hoá vẫn lệch xa target: đo được {measured['input_i']} LUFS"
    )
