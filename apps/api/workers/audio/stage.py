"""Stage `separate` — tách vocals/background (docs §6.3, §9)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import CacheScope, ArtifactKind, StageName
from db.models import SourceVideo
from workers.audio.separator import DEFAULT_MODEL, extract_audio, pick_device, separate


class SeparateStage(Stage):
    name = StageName.SEPARATE
    cache_scope = CacheScope.SOURCE
    provider = "demucs"
    provider_version = DEFAULT_MODEL

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Kết quả KHÔNG phụ thuộc locale — mọi bản ngôn ngữ dùng chung một lần
        tách. Đây là stage đắt nhất pipeline nên chỗ này tiết kiệm nhiều nhất (§16)."""
        return {"model": DEFAULT_MODEL}

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        video_path = ctx.storage.root / source.storage_path
        out_dir = ctx.storage.path_for(ArtifactKind.SEPARATED, project_id=ctx.project_id)

        raw_audio = out_dir / "source_audio.wav"
        if not raw_audio.exists():
            extract_audio(video_path, raw_audio)

        result = separate(raw_audio, out_dir, device=pick_device())

        return StageResult(
            output_ref={
                "vocals": ctx.storage.relative(result.vocals_path),
                "background": ctx.storage.relative(result.background_path),
                "source_audio": ctx.storage.relative(raw_audio),
                "model": result.model,
                "device": result.device,
                "sample_rate": result.sample_rate,
            },
            usage={"gpu_seconds": 0.0},  # đo thật khi có metering (§17)
        )
