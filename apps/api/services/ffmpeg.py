"""Lớp bọc ffmpeg/ffprobe.

Filter graph dựng bằng builder có cấu trúc, KHÔNG nối chuỗi string (§6.15) —
đây là nguồn bug khó debug nhất của loại tool này.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import get_settings


class FFmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    """Kết quả Analyzer (§6.2)."""

    duration_ms: int
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    has_audio: bool
    aspect_ratio: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise FFmpegError(f"lệnh thất bại: {' '.join(cmd[:3])}...\n{proc.stderr[-2000:]}")
    return proc


def probe(path: Path) -> MediaInfo:
    s = get_settings()
    out = _run([
        s.ffprobe_bin, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=120).stdout
    data = json.loads(out)

    streams = data.get("streams", [])
    video = next((x for x in streams if x.get("codec_type") == "video"), None)
    audio = next((x for x in streams if x.get("codec_type") == "audio"), None)

    duration_s = float(data.get("format", {}).get("duration") or 0.0)

    fps = None
    if video and (rate := video.get("avg_frame_rate")):
        num, _, den = rate.partition("/")
        if den and float(den) != 0:
            fps = round(float(num) / float(den), 3)

    return MediaInfo(
        duration_ms=int(round(duration_s * 1000)),
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=fps,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        channels=audio.get("channels") if audio else None,
        has_audio=audio is not None,
        aspect_ratio=video.get("display_aspect_ratio") if video else None,
        raw=data,
    )


class FilterGraph:
    """Builder cho filter_complex — thay vì nối chuỗi bằng tay (§6.15)."""

    def __init__(self) -> None:
        self._chains: list[str] = []
        self._counter = 0

    def label(self, prefix: str = "v") -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    def add(self, inputs: list[str], filter_expr: str, outputs: list[str]) -> FilterGraph:
        src = "".join(f"[{i}]" for i in inputs)
        dst = "".join(f"[{o}]" for o in outputs)
        self._chains.append(f"{src}{filter_expr}{dst}")
        return self

    def build(self) -> str:
        if not self._chains:
            raise FFmpegError("filter graph rỗng")
        return ";".join(self._chains)

    def __len__(self) -> int:
        return len(self._chains)


def run_ffmpeg(args: list[str], *, timeout: int = 1800) -> None:
    s = get_settings()
    _run([s.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", *args], timeout=timeout)


def escape_filter_value(value: Path | str) -> str:
    """Thoát một giá trị (đường dẫn hay chuỗi style) để chèn an toàn vào filter
    mini-language của ffmpeg: `:` là dấu phân cách tham số, `\\`/`'` có ý
    nghĩa escape riêng. Dùng chung cho mọi filter cần escape kiểu này
    (`subtitles`, `drawtext`, `concat`...) — xem `workers/render/stage.py`,
    `services/compose_video.py`."""
    s = str(value)
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
