"""Ghép chunk TTS vào timeline tuyệt đối — docs §9."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from services.audio_timeline import SAMPLE_RATE, PlacedChunk, assemble


def _write_tone(path: Path, duration_ms: int, amplitude: int = 10000) -> Path:
    """WAV mono PCM16 hằng biên độ — dễ kiểm tra chunk có mặt đúng chỗ chưa."""
    n = round(duration_ms / 1000 * SAMPLE_RATE)
    samples = np.full(n, amplitude, dtype=np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SAMPLE_RATE)
        fh.writeframes(samples.tobytes())
    return path


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as fh:
        return np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)


def test_chunk_dat_dung_vi_tri_tuyet_doi(tmp_path):
    chunk = _write_tone(tmp_path / "c0.wav", duration_ms=500, amplitude=10000)
    result = assemble(
        [PlacedChunk(start_ms=1000, path=chunk)], total_duration_ms=3000,
        out_path=tmp_path / "out.wav",
    )
    data = _read(result.path)

    before = round(0.9 * SAMPLE_RATE)  # 900ms — trước khi chunk bắt đầu
    during = round(1.2 * SAMPLE_RATE)  # 1200ms — giữa chunk
    after = round(1.7 * SAMPLE_RATE)   # 1700ms — sau khi chunk kết thúc

    assert data[before] == 0, "im lặng trước vị trí chunk"
    assert data[during] == 10000, "có audio đúng lúc chunk đang phát"
    assert data[after] == 0, "im lặng sau khi chunk kết thúc"


def test_do_dai_track_dung_bang_video(tmp_path):
    chunk = _write_tone(tmp_path / "c0.wav", 200)
    result = assemble(
        [PlacedChunk(0, chunk)], total_duration_ms=5000, out_path=tmp_path / "out.wav",
    )
    data = _read(result.path)
    assert abs(len(data) / SAMPLE_RATE * 1000 - 5000) < 5


def test_nhieu_chunk_khong_cham_nhau(tmp_path):
    c0 = _write_tone(tmp_path / "c0.wav", 300, amplitude=5000)
    c1 = _write_tone(tmp_path / "c1.wav", 300, amplitude=-5000)
    result = assemble(
        [PlacedChunk(0, c0), PlacedChunk(2000, c1)],
        total_duration_ms=3000, out_path=tmp_path / "out.wav",
    )
    assert result.overlaps == []
    data = _read(result.path)
    assert data[round(0.1 * SAMPLE_RATE)] == 5000
    assert data[round(2.1 * SAMPLE_RATE)] == -5000


def test_chong_lan_duoc_ghi_nhan_va_cong_don(tmp_path):
    """BORROW_SILENCE có thể lấn nhẹ vào chunk kế — cộng dồn, không âm thầm bỏ qua."""
    c0 = _write_tone(tmp_path / "c0.wav", 1000, amplitude=5000)
    c1 = _write_tone(tmp_path / "c1.wav", 500, amplitude=3000)
    result = assemble(
        [PlacedChunk(0, c0), PlacedChunk(800, c1)],  # c1 bắt đầu trước khi c0 kết thúc
        total_duration_ms=2000, out_path=tmp_path / "out.wav",
    )
    assert len(result.overlaps) == 1
    assert result.overlaps[0][0] == 800

    data = _read(result.path)
    assert data[round(0.9 * SAMPLE_RATE)] == 8000, "vùng chồng lấn phải CỘNG DỒN biên độ"


def test_khong_tran_ra_ngoai_bien_int16(tmp_path):
    """Chồng lấn nhiều chunk biên độ lớn không được tràn số, phải kẹp về hợp lệ."""
    c0 = _write_tone(tmp_path / "c0.wav", 500, amplitude=30000)
    c1 = _write_tone(tmp_path / "c1.wav", 500, amplitude=30000)
    result = assemble(
        [PlacedChunk(0, c0), PlacedChunk(0, c1)],
        total_duration_ms=1000, out_path=tmp_path / "out.wav",
    )
    data = _read(result.path)
    assert data.max() <= 32767 and data.min() >= -32768


def test_sample_rate_le_bi_tu_choi(tmp_path):
    bad = tmp_path / "bad.wav"
    with wave.open(str(bad), "wb") as fh:
        fh.setnchannels(1); fh.setsampwidth(2); fh.setframerate(16000)
        fh.writeframes(np.zeros(100, dtype=np.int16).tobytes())

    with pytest.raises(ValueError, match="sample rate"):
        assemble([PlacedChunk(0, bad)], 1000, tmp_path / "out.wav")
