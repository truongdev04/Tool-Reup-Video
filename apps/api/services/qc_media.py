"""Đo đạc media thật cho QC — docs §15. Gọi ffmpeg thật, không có logic quyết
định ở đây (logic quyết định nằm ở workers/qc/checks.py, nhận số đã đo)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.config import get_settings


def mean_volume_db(video_path: Path, *, start_ms: int, end_ms: int) -> float:
    """Âm lượng trung bình (dBFS) của một đoạn — dùng để phát hiện mất nhạc
    nền tại khoảng lặng lời thoại (§9, §15: check_background_retained).

    dBFS càng gần 0 càng to; ~-70dB trở xuống coi như im lặng số.
    """
    settings = get_settings()
    duration_s = max(0.05, (end_ms - start_ms) / 1000)
    proc = subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-nostdin",
            "-ss", str(start_ms / 1000), "-t", str(duration_s),
            "-i", str(video_path),
            "-vn", "-af", "volumedetect", "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=120,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", proc.stderr)
    if not match:
        # Không đo được -> coi là im lặng, để check phía FAIL an toàn thay vì
        # âm thầm bỏ qua (§16: nghiêng về phía phát hiện lỗi).
        return -120.0
    return float(match.group(1))


def detect_black_segments(
    video_path: Path, *, min_duration_s: float = 0.5, black_ratio: float = 0.98
) -> list[tuple[float, float]]:
    """Khoảng thời gian (giây) video gần như đen hoàn toàn — §15.

    Dùng filter `blackdetect` có sẵn trong ffmpeg, không cần xử lý frame tay.
    """
    settings = get_settings()
    proc = subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-nostdin",
            "-i", str(video_path),
            "-vf", f"blackdetect=d={min_duration_s}:pic_th={black_ratio}",
            "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=300,
    )
    segments = []
    for m in re.finditer(
        r"black_start:([\d.]+)\s+black_end:([\d.]+)", proc.stderr
    ):
        segments.append((float(m.group(1)), float(m.group(2))))
    return segments


#: Không tính vào "thiếu glyph" — khoảng trắng, xuống dòng, dấu câu ASCII cơ
#: bản gần như font nào cũng có, và thiếu chúng không phải lỗi font (§15).
_SKIP_CHARS = set(" \t\n\r.,!?:;\"'()-–—…")


def missing_glyphs(text: str, font_paths: list[Path]) -> set[str]:
    """Ký tự trong `text` không có glyph ở BẤT KỲ font nào trong `font_paths`
    (§13.2, §14: check_font_coverage) — đo thật bằng bảng `cmap` của font,
    không đoán bằng mắt.

    Font lỗi/không đọc được thì bị BỎ QUA (không tính là "phủ được") — nghiêng
    về phía phát hiện thiếu, đúng nguyên tắc chung của QC (§16).
    """
    from fontTools.ttLib import TTFont

    covered: set[int] = set()
    for path in font_paths:
        try:
            font = TTFont(path, lazy=True)
            for table in font["cmap"].tables:
                covered.update(table.cmap.keys())
        except Exception:  # noqa: BLE001 — font hỏng thì coi như không phủ, không chặn QC
            continue

    return {ch for ch in set(text) if ch not in _SKIP_CHARS and ord(ch) not in covered}
