"""Xuất cue thành file SRT để burn hardsub bằng filter `subtitles` của ffmpeg."""

from __future__ import annotations

from pathlib import Path

from workers.subtitle.splitter import Cue


def _srt_timestamp(ms: int) -> str:
    ms = max(0, ms)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[Cue], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for i, cue in enumerate(cues, start=1):
        blocks.append(
            f"{i}\n{_srt_timestamp(cue.start_ms)} --> {_srt_timestamp(cue.end_ms)}\n"
            + "\n".join(cue.lines)
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path
