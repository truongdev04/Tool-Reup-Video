"""Sinh clip mẫu ~10s để vòng lặp phát triển đủ nhanh mà debug được (docs §21).

Clip có tiếng nói THẬT (sinh bằng `say` của macOS) chứ không phải sine wave —
Whisper phải có lời để nhận dạng thì `stt` và `segment_plan` mới test được.

Cấu trúc cố ý:
  - 2 câu tách nhau bằng khoảng lặng ~1,2s  -> Segment Planner phải tách đúng
    2 đơn vị, và Duration Fitting có khoảng lặng để "mượn" (§7.2)
  - Câu đầu là hook, câu cuối là CTA        -> test đánh dấu transcreation (§6.7)
  - Có nhạc nền                             -> test tách/tái dựng (§9)

Không phụ thuộc file tải về nên kết quả tái lập được y hệt.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from core.config import get_settings

FIXTURE_DIR = Path(__file__).parent
DEFAULT_NAME = "sample_10s_9x16.mp4"

#: Câu đầu = hook, câu cuối = CTA — khớp với luật flag_transcreation (§6.7).
SCRIPT: tuple[str, ...] = (
    "This tool takes one source video and turns it into many language versions.",
    "Follow for more automation tips.",
)

GAP_SECONDS = 1.2
VOICE = "Samantha"


def _say(text: str, out: Path) -> Path:
    """Sinh giọng đọc bằng `say` của macOS."""
    subprocess.run(
        # Không truyền --data-format: một số bản macOS không nhận. Để ffmpeg
        # resample ở bước sau.
        ["say", "-v", VOICE, "-o", str(out), text],
        check=True, capture_output=True, timeout=60,
    )
    return out


def make_sample(path: Path | None = None) -> Path:
    """Tạo clip 9:16 có tiếng nói thật. Đã tồn tại thì trả về luôn (idempotent)."""
    out = Path(path) if path else FIXTURE_DIR / DEFAULT_NAME
    if out.exists():
        return out
    if not shutil.which("say"):
        raise RuntimeError("fixture cần lệnh `say` của macOS để sinh tiếng nói")

    s = get_settings()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # 1. Sinh từng câu thành file riêng.
        parts = [_say(text, tmpdir / f"line{i}.aiff") for i, text in enumerate(SCRIPT)]

        # 2. Nối các câu, chèn khoảng lặng giữa chúng.
        speech = tmpdir / "speech.wav"
        inputs: list[str] = []
        filters: list[str] = []
        for i, part in enumerate(parts):
            inputs += ["-i", str(part)]
            filters.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=s16:channel_layouts=mono[s{i}]")

        silence_idx = len(parts)
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={GAP_SECONDS}"]
        filters.append(f"[{silence_idx}:a]aformat=sample_fmts=s16:channel_layouts=mono[gap]")

        concat_in = "[s0][gap]" + "".join(f"[s{i}]" for i in range(1, len(parts)))
        filters.append(f"{concat_in}concat=n={len(parts) + 1}:v=0:a=1[out]")

        subprocess.run(
            [s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", *inputs,
             "-filter_complex", ";".join(filters), "-map", "[out]", str(speech)],
            check=True, capture_output=True, timeout=120,
        )

        # 3. Đo độ dài thật để video khớp audio.
        dur = float(subprocess.run(
            [s.ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(speech)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip())

        # 4. Ghép hình + giọng + nhạc nền.
        subprocess.run(
            [s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={dur:.3f}",
             "-i", str(speech),
             "-f", "lavfi", "-i", f"sine=frequency=330:duration={dur:.3f},volume=0.06",
             "-filter_complex",
             "[1:a]aformat=channel_layouts=stereo[v];"
             "[2:a]aformat=channel_layouts=stereo[m];"
             "[v][m]amix=inputs=2:duration=first:weights=1 0.5[aout]",
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)],
            check=True, capture_output=True, timeout=180,
        )

    return out


if __name__ == "__main__":
    print(make_sample())
