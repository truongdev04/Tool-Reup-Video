"""Stage `timeline_assembly` — docs §4, §9.

Ghép từng chunk TTS vào đúng vị trí tuyệt đối `unit.start_ms` trong video gốc.
Không nối đuôi nhau — nhờ vậy khoảng lặng giữa các lời thoại và các mốc hình
ảnh (chuyển cảnh, nhạc nền gốc) vẫn đúng chỗ. Track này là phần "giọng nói";
trộn với `background.wav` diễn ra ở stage `render`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, StageName
from db.models import OutputFile, SourceVideo, TranslationUnit, TTSChunk
from core.hashing import file_checksum
from services.audio_timeline import PlacedChunk, assemble


class TimelineAssemblyStage(Stage):
    name = StageName.TIMELINE_ASSEMBLY

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        total_duration_ms = (source.media_info or {}).get("duration_ms")
        if not total_duration_ms:
            raise NonRetryableError(
                "source_videos.media_info thiếu duration_ms — chạy stage analyze trước"
            )

        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        if not units:
            raise NonRetryableError("chưa có translation_units — chạy segment_plan trước")

        placed: list[PlacedChunk] = []
        for unit in units:
            chunk = ctx.session.scalars(
                select(TTSChunk).where(TTSChunk.translation_unit_id == unit.id)
            ).first()
            if chunk is None or not chunk.audio_path:
                raise NonRetryableError(f"đơn vị {unit.idx} chưa có audio — chạy stage tts trước")
            placed.append(
                PlacedChunk(start_ms=unit.start_ms, path=ctx.storage.root / chunk.audio_path)
            )

        out_path = ctx.storage.path_for(
            ArtifactKind.ASSEMBLED, project_id=ctx.project_id, job_id=ctx.job_id,
            filename="voice.wav",
        )
        result = assemble(placed, total_duration_ms, out_path)

        self._save_output_file(ctx, out_path, total_duration_ms)

        return StageResult(
            output_ref={
                "path": ctx.storage.relative(out_path),
                "total_duration_ms": result.total_duration_ms,
                "chunks_placed": len(placed),
                "overlaps": result.overlaps,
            },
            needs_review=bool(result.overlaps),
            note=(
                f"{len(result.overlaps)} chỗ chồng lấn giữa các chunk — xem lại ở QC (§15)"
                if result.overlaps
                else None
            ),
        )

    def _save_output_file(self, ctx: StageContext, path, duration_ms: int) -> None:
        """Idempotent (§11.1): thay bản ghi ASSEMBLED cũ của job này, không cộng dồn."""
        existing = ctx.session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == ctx.job_id,
                OutputFile.kind == ArtifactKind.ASSEMBLED,
            )
        ).all()
        for row in existing:
            ctx.session.delete(row)

        ctx.session.add(
            OutputFile(
                render_job_id=ctx.job_id,
                kind=ArtifactKind.ASSEMBLED,
                storage_path=ctx.storage.relative(path),
                checksum=file_checksum(path),
                size_bytes=path.stat().st_size,
                media_info={"duration_ms": duration_ms},
            )
        )
        ctx.session.flush()
