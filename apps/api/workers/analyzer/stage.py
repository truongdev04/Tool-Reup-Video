"""Stage `analyze` — Video Analyzer (docs §6.2)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import CacheScope, StageName
from db.models import SourceVideo
from services.ffmpeg import probe


class AnalyzeStage(Stage):
    name = StageName.ANALYZE
    cache_scope = CacheScope.SOURCE

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        info = probe(ctx.storage.root / source.storage_path)

        media = asdict(info)
        media.pop("raw", None)  # ffprobe raw quá dài, không lưu vào DB
        source.media_info = media
        ctx.session.flush()

        warnings: list[str] = []
        if not info.has_audio:
            warnings.append("video không có audio track — không chạy được STT/TTS")
        if info.duration_ms == 0:
            warnings.append("duration = 0")

        return StageResult(
            output_ref={
                "source_video_id": source.id,
                "duration_ms": info.duration_ms,
                "resolution": f"{info.width}x{info.height}",
                "fps": info.fps,
                "has_audio": info.has_audio,
                "warnings": warnings,
            },
            needs_review=bool(warnings),
            note="; ".join(warnings) or None,
        )
