"""Sinh logo/intro/outro placeholder cho demo `compose` khi chưa có asset
thương hiệu thật.

Cùng tinh thần với `make_fixture.py`: tổng hợp bằng ffmpeg lavfi, không phụ
thuộc file tải về, kết quả tái lập được y hệt. Chỉ dùng khi
`Project.brand_profile_id` chưa được set — xem `workers/compose/stage.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.config import get_settings

DEFAULT_NAME = "demo_logo.png"
DEFAULT_TEXT = "TOOL REUP"
#: Màu accent của chính dev viewer (api/static/styles.css --accent) — để logo
#: demo trông nhất quán với phần còn lại thay vì một màu ngẫu nhiên.
DEFAULT_COLOR = "0x0D6D78"

#: Resolution "gốc" của clip intro/outro placeholder — không cần khớp video
#: nguồn ở bước sinh này, `prepare_clip_for_concat` (§6.14) sẽ scale/pad về
#: đúng resolution thật ngay trước khi nối. 9:16 vì đây là aspect mặc định
#: của clip fixture dùng để dev (`tests/fixtures/sample_10s_9x16.mp4`).
_CLIP_SIZE = "608x1080"
_INTRO_TEXT = "TOOL REUP"
_OUTRO_TEXT = "Theo dõi để xem thêm!"
_CLIP_DURATION_S = 1.5

#: Placeholder mặc định cho `BrandProfile.cta_config` (§6.14) — hiện ở
#: `duration_ms` cuối cùng của video CHÍNH (không tính intro/outro, xem
#: `workers/compose/stage.py`). Text chung chung, không dịch theo locale
#: (compose vẫn `cache_scope=SOURCE` — quyết định giữ nguyên kiến trúc, xem
#: compose.md).
DEFAULT_CTA_CONFIG: dict = {
    "text": "Theo dõi để xem thêm!",
    "position": "bottom_center",
    "duration_ms": 3000,
    "fontsize_pct": 4.0,
    "color": "white",
}


def make_demo_logo(path: Path | None = None, *, text: str = DEFAULT_TEXT) -> Path:
    """Logo chữ nhật đơn giản, nền màu + chữ trắng. Đã tồn tại thì trả về luôn
    (idempotent — tính chất chung của mọi fixture trong dự án)."""
    out = Path(path) if path else Path(__file__).parent / DEFAULT_NAME
    if out.exists():
        return out

    s = get_settings()
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={DEFAULT_COLOR}:s=480x140",
            "-vf",
            f"drawtext=text='{text}':fontsize=48:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2",
            "-frames:v", "1", str(out),
        ],
        check=True, capture_output=True, timeout=30,
    )
    return out


def _make_demo_clip(path: Path, *, text: str, color: str) -> Path:
    """Clip màu nền + tên brand căn giữa — dùng chung cho intro và outro,
    chỉ khác text/màu. Idempotent như `make_demo_logo`."""
    if path.exists():
        return path

    s = get_settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={_CLIP_SIZE}:d={_CLIP_DURATION_S}",
            "-vf",
            f"drawtext=text='{text}':fontsize=64:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True, capture_output=True, timeout=30,
    )
    return path


def make_demo_intro(path: Path | None = None) -> Path:
    out = Path(path) if path else Path(__file__).parent / "demo_intro.mp4"
    return _make_demo_clip(out, text=_INTRO_TEXT, color=DEFAULT_COLOR)


def make_demo_outro(path: Path | None = None) -> Path:
    #: Màu khác intro để dev nhìn ra ngay hai đoạn ghép đúng thứ tự khi xem thử.
    out = Path(path) if path else Path(__file__).parent / "demo_outro.mp4"
    return _make_demo_clip(out, text=_OUTRO_TEXT, color="0x1A1A2E")


if __name__ == "__main__":
    print(make_demo_logo())
    print(make_demo_intro())
    print(make_demo_outro())
