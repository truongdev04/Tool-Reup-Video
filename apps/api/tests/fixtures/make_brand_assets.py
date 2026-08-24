"""Sinh logo placeholder cho demo `compose` khi chưa có asset thương hiệu thật.

Cùng tinh thần với `make_fixture.py`: tổng hợp bằng ffmpeg lavfi, không phụ
thuộc file tải về, kết quả tái lập được y hệt. Chỉ dùng khi
`Project.brand_profile_id` chưa được set — xem `workers/compose/stage.py`.
"""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings

DEFAULT_NAME = "demo_logo.png"
DEFAULT_TEXT = "TOOL REUP"
#: Màu accent của chính dev viewer (api/static/styles.css --accent) — để logo
#: demo trông nhất quán với phần còn lại thay vì một màu ngẫu nhiên.
DEFAULT_COLOR = "0x0D6D78"


def make_demo_logo(path: Path | None = None, *, text: str = DEFAULT_TEXT) -> Path:
    """Logo chữ nhật đơn giản, nền màu + chữ trắng. Đã tồn tại thì trả về luôn
    (idempotent — tính chất chung của mọi fixture trong dự án)."""
    out = Path(path) if path else Path(__file__).parent / DEFAULT_NAME
    if out.exists():
        return out

    import subprocess

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


if __name__ == "__main__":
    print(make_demo_logo())
