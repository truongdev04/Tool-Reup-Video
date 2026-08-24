"""Áp logo/CTA/intro-outro lên video — docs §6.14. Gọi ffmpeg thật, xác minh
bằng cách lấy mẫu pixel/âm lượng thay vì chỉ kiểm tra file không lỗi — nhất
quán với phong cách test_qc_media.py/test_audio_mix.py của dự án."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.config import get_settings
from services.compose_video import concat_clips, overlay_cta, overlay_logo, prepare_clip_for_concat
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


# ---------------------------------------------------------------------------
# prepare_clip_for_concat / concat_clips — §6.14 intro/outro
# ---------------------------------------------------------------------------


def test_prepare_clip_chuan_hoa_dung_resolution_fps_sar(tmp_path):
    """Input khác hẳn resolution/fps nguồn (640x480@30) — output phải khớp
    ĐÚNG resolution/fps target (320x240@25) và SAR=1:1, không thì `concat`
    sẽ từ chối nối (đã gặp lỗi SAR lệch 18221:18225 khi test bằng pipeline
    thật, xem .claude/rules/compose.md)."""
    src = _make_clip(tmp_path / "src.mp4", "red", size="640x480", duration=1.0)
    out = prepare_clip_for_concat(src, tmp_path / "prepared.mp4", width=320, height=240, fps=25)

    info = probe(out)
    assert (info.width, info.height) == (320, 240)
    assert info.fps == 25
    assert info.aspect_ratio in ("4:3", "320:240"), f"SAR/DAR bất thường: {info.raw}"


def test_noi_hai_clip_dung_thu_tu_va_tong_thoi_luong(tmp_path):
    a = _make_clip(tmp_path / "a.mp4", "red", size="320x240", duration=1.0)
    b = _make_clip(tmp_path / "b.mp4", "blue", size="320x240", duration=2.0)
    a_prepared = prepare_clip_for_concat(a, tmp_path / "a_p.mp4", width=320, height=240, fps=25)

    out = tmp_path / "joined.mp4"
    concat_clips([a_prepared, b], out)

    assert probe(out).duration_ms == pytest.approx(3000, abs=100)
    assert _is_red(_sample_pixel(out, 160, 120)), "0.5s đầu (trong clip A) phải màu đỏ"
    run_ffmpeg(["-y", "-ss", "1.8", "-i", str(out), "-frames:v", "1", str(tmp_path / "mid.png")])
    assert _is_blue(_sample_pixel(tmp_path / "mid.png", 160, 120)), "sau 1s (trong clip B) phải màu xanh"


def test_noi_duoi_2_clip_bao_loi_ro_rang(tmp_path, blue_video):
    with pytest.raises(ValueError, match="ít nhất 2 clip"):
        concat_clips([blue_video], tmp_path / "x.mp4")


# ---------------------------------------------------------------------------
# overlay_cta — §6.14 CTA
# ---------------------------------------------------------------------------


@pytest.fixture
def cta_fontfile() -> Path:
    return get_settings().fonts_dir / "NotoSans-Regular.ttf"


def test_cta_chi_hien_trong_dung_khung_thoi_gian(tmp_path, cta_fontfile):
    src = _make_clip(tmp_path / "src.mp4", "blue", size="320x240", duration=3.0)
    out = tmp_path / "with_cta.mp4"
    overlay_cta(
        src, out, text="Theo dõi để xem thêm!", fontfile=cta_fontfile,
        start_ms=1000, duration_ms=1000, position="bottom_center",
    )

    # Box vẽ toàn bộ bề rộng dòng chữ — lấy mẫu NGOÀI vùng chữ (góc trên) để
    # chỉ đo hộp nền đen, không lẫn glyph trắng.
    before = _sample_pixel(_frame_at(out, 0.3, tmp_path / "f0.png"), 5, 5)
    during = _sample_pixel(_frame_at(out, 1.5, tmp_path / "f1.png"), 160, 220)
    after = _sample_pixel(_frame_at(out, 2.5, tmp_path / "f2.png"), 5, 5)

    assert _is_blue(before), "trước khung thời gian phải chưa có CTA (chỉ nền xanh)"
    assert _is_blue(after), "sau khung thời gian CTA phải biến mất"
    assert not _is_blue(during), "trong khung thời gian phải có hộp CTA đè lên nền xanh"


def test_cta_vi_tri_khong_hop_le_bao_loi_ro_rang(tmp_path, cta_fontfile, blue_video):
    with pytest.raises(ValueError, match="vị trí CTA"):
        overlay_cta(
            blue_video, tmp_path / "x.mp4", text="x", fontfile=cta_fontfile,
            start_ms=0, duration_ms=100, position="middle-ish",
        )


def _frame_at(video_path: Path, t: float, out_png: Path) -> Path:
    run_ffmpeg(["-y", "-ss", str(t), "-i", str(video_path), "-frames:v", "1", str(out_png)])
    return out_png
