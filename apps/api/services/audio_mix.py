"""Trộn giọng đọc với nhạc nền gốc và chuẩn hoá loudness — docs §9.

Track cuối là `TTS + background gốc`, KHÔNG PHẢI thay thế: thay nguyên track
audio bằng TTS là mất sạch nhạc nền, tiếng động và không khí của video gốc.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from core.config import get_settings

#: Mục tiêu loudness của phần lớn nền tảng lớn (§9) — xác minh lại trước khi
#: chốt Phase 5, con số này thay đổi theo thời gian và theo nền tảng.
TARGET_I = -14.0
TARGET_TP = -1.5
TARGET_LRA = 11.0


def mix_voice_and_background(
    voice_path: Path,
    background_path: Path,
    out_path: Path,
    *,
    voice_gain: float = 1.0,
    background_gain: float = 0.6,
) -> Path:
    """Trộn giọng (chiếm ưu thế) với nhạc nền (giảm âm lượng để không lấn giọng)."""
    settings = get_settings()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(voice_path), "-i", str(background_path),
            "-filter_complex",
            f"[0:a]volume={voice_gain}[v];[1:a]volume={background_gain}[b];"
            f"[v][b]amix=inputs=2:duration=first:dropout_transition=0[out]",
            "-map", "[out]", "-c:a", "pcm_s16le", str(out_path),
        ],
        check=True, capture_output=True, timeout=300,
    )
    return out_path


def measure_loudnorm(path: Path) -> dict:
    """Lượt 1: đo loudness thật của file — dùng cho lượt 2 (§9).

    Một lượt loudnorm cho kết quả không ổn định giữa các file; đo trước rồi áp
    lại bằng thông số đã đo (`linear=true`) mới cho kết quả nhất quán.
    """
    settings = get_settings()
    proc = subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
            "-i", str(path),
            "-af", f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=300,
    )
    match = re.search(r"\{(?:[^{}]|\n)*\}", proc.stderr)
    if not match:
        raise RuntimeError(f"không đọc được kết quả đo loudnorm: {proc.stderr[-500:]}")
    return json.loads(match.group())


def loudnorm_two_pass(path: Path, out_path: Path) -> Path:
    """Chuẩn hoá về TARGET_I LUFS bằng loudnorm hai lượt (§9)."""
    settings = get_settings()
    measured = measure_loudnorm(path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(path),
            "-af", (
                f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:"
                f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}:linear=true:print_format=summary"
            ),
            "-c:a", "pcm_s16le", str(out_path),
        ],
        check=True, capture_output=True, timeout=300,
    )
    return out_path
