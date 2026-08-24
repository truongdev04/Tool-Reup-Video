"""Áp logo/watermark lên video — docs §6.14.

Không phụ thuộc locale (branding giống nhau cho mọi bản ngôn ngữ), nên đây là
bước CHẠY MỘT LẦN cho cả video, không phải mỗi job (xem CacheScope.SOURCE ở
`workers/compose/stage.py`). Output không giữ audio — `render` sẽ thay bằng
track đã tái dựng (§9), giữ audio ở đây chỉ tốn dung lượng vô ích.
"""

from __future__ import annotations

from pathlib import Path

from services.ffmpeg import FilterGraph, probe, run_ffmpeg

_POSITION_EXPR: dict[str, tuple[str, str]] = {
    "top_left": ("margin", "margin"),
    "top_right": ("W-w-margin", "margin"),
    "bottom_left": ("margin", "H-h-margin"),
    "bottom_right": ("W-w-margin", "H-h-margin"),
    "center": ("(W-w)/2", "(H-h)/2"),
}


def overlay_logo(
    video_path: Path,
    logo_path: Path,
    out_path: Path,
    *,
    position: str = "bottom_right",
    opacity: float = 0.85,
    scale_pct: float = 12.0,
    margin_pct: float = 3.0,
) -> Path:
    """Chèn logo vào video, không giữ audio. Bề rộng logo tính theo % bề rộng
    video để không vỡ tỉ lệ khi đổi resolution nguồn."""
    if position not in _POSITION_EXPR:
        raise ValueError(f"vị trí logo không hợp lệ: {position}. Đang hỗ trợ: {sorted(_POSITION_EXPR)}")

    info = probe(video_path)
    if not info.width:
        raise ValueError(f"không đọc được kích thước video: {video_path}")

    logo_w = max(1, round(info.width * scale_pct / 100))
    margin = max(0, round(info.width * margin_pct / 100))
    x_expr, y_expr = _POSITION_EXPR[position]
    x_expr = x_expr.replace("margin", str(margin))
    y_expr = y_expr.replace("margin", str(margin))

    graph = FilterGraph()
    graph.add(
        ["1:v"],
        f"format=rgba,colorchannelmixer=aa={opacity},scale={logo_w}:-1",
        ["logo"],
    )
    graph.add(["0:v", "logo"], f"overlay=x={x_expr}:y={y_expr}", ["vout"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(video_path), "-i", str(logo_path),
        "-filter_complex", graph.build(),
        "-map", "[vout]", "-an",
        "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p",
        str(out_path),
    ])
    return out_path
