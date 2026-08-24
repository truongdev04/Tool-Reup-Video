"""Đo đạc media thật cho QC — docs §15. Dùng ffmpeg lavfi để sinh input tổng
hợp, không cần file mẫu ngoài."""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings
from services.ffmpeg import run_ffmpeg
from services.qc_media import detect_black_segments, mean_volume_db


def _make_clip(path: Path, *, color: str, duration_s: float, tone_db: float | None) -> Path:
    """Clip tổng hợp: `color` cho hình, `tone_db` là biên độ sine (None = im lặng)."""
    settings = get_settings()
    audio = (
        f"sine=frequency=440:duration={duration_s}"
        + (f",volume={10 ** (tone_db / 20):.6f}" if tone_db is not None else ",volume=0")
    )
    run_ffmpeg([
        "-f", "lavfi", "-i", f"color=c={color}:size=320x240:rate=10:duration={duration_s}",
        "-f", "lavfi", "-i", audio,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ])
    return path


def test_video_toan_mau_den_bi_phat_hien(tmp_path):
    clip = _make_clip(tmp_path / "black.mp4", color="black", duration_s=2.0, tone_db=-20)
    segments = detect_black_segments(clip, min_duration_s=0.5)
    assert segments, "clip toàn màu đen phải được phát hiện"
    start, end = segments[0]
    assert end - start >= 0.5


def test_video_binh_thuong_khong_bao_gio_bi_bao_den(tmp_path):
    clip = _make_clip(tmp_path / "normal.mp4", color="blue", duration_s=2.0, tone_db=-20)
    assert detect_black_segments(clip, min_duration_s=0.5) == []


def test_doan_co_tieng_do_muc_cao_hon_doan_im_lang(tmp_path):
    loud = _make_clip(tmp_path / "loud.mp4", color="blue", duration_s=1.0, tone_db=-10)
    quiet = _make_clip(tmp_path / "quiet.mp4", color="blue", duration_s=1.0, tone_db=None)

    loud_db = mean_volume_db(loud, start_ms=0, end_ms=1000)
    quiet_db = mean_volume_db(quiet, start_ms=0, end_ms=1000)
    assert loud_db > quiet_db + 20, "đoạn có tiếng phải đo được to hơn hẳn đoạn im lặng"


def test_doan_im_lang_gan_am_vo_cung(tmp_path):
    clip = _make_clip(tmp_path / "silent.mp4", color="blue", duration_s=1.0, tone_db=None)
    assert mean_volume_db(clip, start_ms=0, end_ms=1000) < -50
