"""Áp logo/watermark, CTA và intro/outro lên video — docs §6.14.

Không phụ thuộc locale (branding giống nhau cho mọi bản ngôn ngữ), nên đây là
bước CHẠY MỘT LẦN cho cả video, không phải mỗi job (xem CacheScope.SOURCE ở
`workers/compose/stage.py`). Output không giữ audio — `render` sẽ thay bằng
track đã tái dựng (§9), giữ audio ở đây chỉ tốn dung lượng vô ích.
"""

from __future__ import annotations

from pathlib import Path

from services.ffmpeg import FilterGraph, escape_filter_value, probe, run_ffmpeg

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


_CTA_POSITION_EXPR: dict[str, tuple[str, str]] = {
    "bottom_center": ("(w-text_w)/2", "h-text_h-margin"),
    "top_center": ("(w-text_w)/2", "margin"),
    "bottom_left": ("margin", "h-text_h-margin"),
    "bottom_right": ("w-text_w-margin", "h-text_h-margin"),
}


def overlay_cta(
    video_path: Path,
    out_path: Path,
    *,
    text: str,
    fontfile: Path,
    start_ms: int,
    duration_ms: int,
    position: str = "bottom_center",
    fontsize_pct: float = 4.0,
    color: str = "white",
    box_opacity: float = 0.55,
    margin_pct: float = 4.0,
) -> Path:
    """Vẽ text CTA đè lên video, chỉ hiện trong khung [start_ms, start_ms+duration_ms)
    (§6.14) — dùng `enable='between(t,...)'` của `drawtext`, không cắt/ghép
    clip riêng cho đoạn có CTA.

    Dùng `textfile=` thay vì `text=` inline: `text` do người dùng nhập qua
    `BrandProfile.cta_config` (§2.2 — không hard-code), không phải hằng số
    trong source. Thoát tay chuỗi text tự do (dấu `:`, `'`, `%`, xuống dòng)
    cho ffmpeg mini-language là nguồn lỗi khó debug — `textfile` né hoàn toàn
    lớp thoát đó, chỉ còn phải thoát ĐƯỜNG DẪN file (ít rủi ro hơn nhiều).

    `fontfile` nên trỏ thẳng vào font đã bundle (`services/fonts.py`) thay vì
    dựa vào tên family qua fontconfig — CTA cần hiển thị đúng dấu tiếng Việt/
    ký tự đặc biệt bất kể máy chạy render có cài font đó theo tên hay không.
    """
    if position not in _CTA_POSITION_EXPR:
        raise ValueError(f"vị trí CTA không hợp lệ: {position}. Đang hỗ trợ: {sorted(_CTA_POSITION_EXPR)}")

    info = probe(video_path)
    if not info.width:
        raise ValueError(f"không đọc được kích thước video: {video_path}")

    fontsize = max(1, round(info.width * fontsize_pct / 100))
    margin = max(0, round(info.width * margin_pct / 100))
    x_expr, y_expr = _CTA_POSITION_EXPR[position]
    x_expr = x_expr.replace("margin", str(margin))
    y_expr = y_expr.replace("margin", str(margin))
    start_s, end_s = start_ms / 1000, (start_ms + duration_ms) / 1000

    out_path.parent.mkdir(parents=True, exist_ok=True)
    textfile = out_path.with_suffix(".cta.txt")
    textfile.write_text(text, encoding="utf-8")

    try:
        graph = FilterGraph()
        graph.add(
            ["0:v"],
            (
                f"drawtext=fontfile='{escape_filter_value(fontfile)}':"
                f"textfile='{escape_filter_value(textfile)}':"
                f"fontsize={fontsize}:fontcolor={color}:x={x_expr}:y={y_expr}:"
                f"box=1:boxcolor=black@{box_opacity}:boxborderw={max(2, fontsize // 6)}:"
                f"enable='between(t\\,{start_s:.3f}\\,{end_s:.3f})'"
            ),
            ["vout"],
        )
        run_ffmpeg([
            "-i", str(video_path),
            "-filter_complex", graph.build(),
            "-map", "[vout]", "-an",
            "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p",
            str(out_path),
        ])
    finally:
        textfile.unlink(missing_ok=True)
    return out_path


def prepare_clip_for_concat(
    clip_path: Path, out_path: Path, *, width: int, height: int, fps: float,
) -> Path:
    """Scale+pad một clip (intro/outro/chính) về ĐÚNG resolution/fps/SAR trước
    khi nối (§6.14) — filter `concat` đòi mọi input khớp CẢ SAR (sample aspect
    ratio), không chỉ resolution/fps: `scale`+`pad` một mình có thể ra SAR lệch
    kiểu 18221:18225 thay vì 1:1 (đã gặp lỗi `concat` từ chối chạy vì lệch này
    khi test thật — sửa bằng `setsar=1`, ép cả 3 clip qua CÙNG một filter chain
    này, kể cả clip chính, để không có input nào "thoát" chuẩn hoá). Áp dụng
    cho CẢ clip placeholder tự sinh lẫn clip người dùng tự cung cấp (khác
    resolution/fps nguồn là chuyện bình thường, không phải lỗi cần chặn)."""
    graph = FilterGraph()
    graph.add(
        ["0:v"],
        (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps}"
        ),
        ["vout"],
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(clip_path),
        "-filter_complex", graph.build(),
        "-map", "[vout]", "-an",
        "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p",
        str(out_path),
    ])
    return out_path


def concat_clips(clips: list[Path], out_path: Path) -> Path:
    """Nối nhiều clip LIÊN TIẾP thành một video (§6.14: intro + main + outro)
    bằng filter `concat`, không phải concat demuxer — demuxer đòi cùng codec
    param y hệt giữa các file, filter chịu được input khác nhau MIỄN cùng
    resolution/fps/pix_fmt (caller phải tự đảm bảo bằng
    `prepare_clip_for_concat` trước khi gọi hàm này).

    Không giữ audio — cùng lý do `overlay_logo`/`overlay_cta`."""
    if len(clips) < 2:
        raise ValueError("cần ít nhất 2 clip để nối")

    graph = FilterGraph()
    graph.add([f"{i}:v" for i in range(len(clips))], f"concat=n={len(clips)}:v=1:a=0", ["vout"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    for clip in clips:
        args += ["-i", str(clip)]
    args += [
        "-filter_complex", graph.build(),
        "-map", "[vout]", "-an",
        "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    run_ffmpeg(args)
    return out_path
