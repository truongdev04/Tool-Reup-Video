"""Áp logo lên video — docs §6.14. Gọi ffmpeg thật, xác minh bằng cách lấy mẫu
pixel thay vì chỉ kiểm tra file không lỗi — nhất quán với phong cách
test_qc_media.py/test_audio_mix.py của dự án."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.config import get_settings
from services.compose_video import overlay_logo
from services.ffmpeg import probe, run_ffmpeg


def _make_clip(path: Path, color: str, *, size: str = "320x240", duration: float = 1.0) -> Path:
    settings = get_settings()
    subprocess.run(
        [settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={duration}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=30,
    )
    return path


def _sample_pixel(video_path: Path, x: int, y: int, *, block: int = 4) -> tuple[int, int, int]:
    """Màu trung bình một khối nhỏ quanh (x,y) — kích thước crop phải CHẴN để
    tương thích chroma subsampling yuv420p, và lấy trung bình thay vì 1 pixel
    để tránh artifact nén ở rìa hình."""
    settings = get_settings()
    x, y = x - x % 2, y - y % 2  # ép toạ độ chẵn
    proc = subprocess.run(
        [settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error",
         "-i", str(video_path), "-vf", f"crop={block}:{block}:{x}:{y}",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=30,
    )
    data = proc.stdout
    assert len(data) >= block * block * 3, (
        f"không lấy được vùng tại ({x},{y}): {proc.stderr[-300:]}"
    )
    n = block * block
    r = sum(data[i * 3] for i in range(n)) // n
    g = sum(data[i * 3 + 1] for i in range(n)) // n
    b = sum(data[i * 3 + 2] for i in range(n)) // n
    return r, g, b


def _is_blue(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return b > 150 and r < 100 and g < 100


def _is_red(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > 150 and g < 100 and b < 100


@pytest.fixture
def blue_video(tmp_path):
    return _make_clip(tmp_path / "base.mp4", "blue")


@pytest.fixture
def red_logo(tmp_path):
    return _make_clip(tmp_path / "logo.mp4", "red", size="100x100")


def test_logo_xuat_hien_dung_vi_tri_bottom_right(tmp_path, blue_video, red_logo):
    # red_logo.mp4 là video; overlay_logo cần ẢNH — trích 1 frame làm PNG.
    logo_png = tmp_path / "logo.png"
    run_ffmpeg(["-i", str(red_logo), "-frames:v", "1", str(logo_png)])

    out = tmp_path / "composed.mp4"
    overlay_logo(
        blue_video, logo_png, out,
        position="bottom_right", opacity=1.0, scale_pct=30, margin_pct=2,
    )
    # video 320x240, logo rộng 96px (30%), margin 6px (2%) -> logo chiếm
    # x:[218,314] y:[138,234]. Lấy mẫu SÂU trong từng vùng, tránh rìa nén.
    inside_logo = _sample_pixel(out, 260, 180)
    inside_background = _sample_pixel(out, 20, 20)

    assert _is_red(inside_logo), f"kỳ vọng đỏ trong vùng logo, được {inside_logo}"
    assert _is_blue(inside_background), f"kỳ vọng xanh ngoài vùng logo, được {inside_background}"


def test_vi_tri_top_left_dat_dung_goc(tmp_path, blue_video, red_logo):
    logo_png = tmp_path / "logo.png"
    run_ffmpeg(["-i", str(red_logo), "-frames:v", "1", str(logo_png)])

    out = tmp_path / "composed.mp4"
    overlay_logo(blue_video, logo_png, out, position="top_left", opacity=1.0, scale_pct=30, margin_pct=2)
    # logo chiếm x:[6,102] y:[6,102] -> mẫu trong logo và mẫu ở góc đối diện.
    assert _is_red(_sample_pixel(out, 50, 50))
    assert _is_blue(_sample_pixel(out, 280, 200))


def test_khong_giu_audio(tmp_path, blue_video, red_logo):
    """Render sẽ thay audio bằng track đã tái dựng — giữ audio ở compose vô ích."""
    logo_png = tmp_path / "logo.png"
    run_ffmpeg(["-i", str(red_logo), "-frames:v", "1", str(logo_png)])

    out = tmp_path / "composed.mp4"
    overlay_logo(blue_video, logo_png, out, position="center")
    assert not probe(out).has_audio


def test_vi_tri_khong_hop_le_bao_loi_ro_rang(tmp_path, blue_video, red_logo):
    logo_png = tmp_path / "logo.png"
    run_ffmpeg(["-i", str(red_logo), "-frames:v", "1", str(logo_png)])

    with pytest.raises(ValueError, match="vị trí logo"):
        overlay_logo(blue_video, logo_png, tmp_path / "x.mp4", position="middle-ish")
