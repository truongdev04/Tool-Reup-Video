"""Sinh clip mẫu ~10s để vòng lặp phát triển đủ nhanh mà debug được (docs §21).

Dùng lavfi nên không cần tải file ngoài và kết quả tái lập được y hệt.
Clip có: hình chuyển động + 2 "đoạn nói" cách nhau bằng khoảng lặng (để test
Segment Planner và Duration Fitting) + nhạc nền nhẹ (để test tách/tái dựng §9).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.config import get_settings

FIXTURE_DIR = Path(__file__).parent
DEFAULT_NAME = "sample_10s_9x16.mp4"


def make_sample(path: Path | None = None, *, seconds: int = 10) -> Path:
    """Tạo clip 9:16, 30fps, có audio. Đã tồn tại thì trả về luôn (idempotent)."""
    out = Path(path) if path else FIXTURE_DIR / DEFAULT_NAME
    if out.exists():
        return out

    s = get_settings()
    out.parent.mkdir(parents=True, exist_ok=True)

    # Giọng giả lập: 2 chuỗi sine bật/tắt, xen khoảng lặng -> có cấu trúc segment.
    speech = (
        f"sine=frequency=220:duration={seconds},"
        f"volume='if(between(t,0.5,3.5)+between(t,5.0,8.5),0.6,0)':eval=frame"
    )
    music = f"sine=frequency=440:duration={seconds},volume=0.08"

    subprocess.run(
        [
            s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", speech,
            "-f", "lavfi", "-i", music,
            "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=shortest[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            str(out),
        ],
        check=True, capture_output=True, timeout=120,
    )
    return out


if __name__ == "__main__":
    print(make_sample())
