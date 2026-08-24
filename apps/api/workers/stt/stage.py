"""Stage `stt` — Speech-to-Text (docs §6.4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import CacheScope, ArtifactKind, StageName
from db.models import STTSegment, SourceVideo, Transcript
from services.presets import to_language_code
from workers.stt.transcriber import resolve_model_for_env, transcribe


class STTStage(Stage):
    name = StageName.STT
    cache_scope = CacheScope.SOURCE
    provider = "mlx-whisper"

    @property
    def provider_version(self) -> str:  # type: ignore[override]
        return resolve_model_for_env()

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Transcript KHÔNG phụ thuộc locale đích — mọi bản ngôn ngữ dùng chung."""
        return {"model": resolve_model_for_env()}

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        # Ưu tiên track vocals đã tách: STT trên giọng sạch chính xác hơn nhiều
        # so với chạy trên audio còn lẫn nhạc nền.
        separated = ctx.storage.path_for(ArtifactKind.SEPARATED, project_id=ctx.project_id)
        vocals = separated / "vocals.wav"
        audio_path = vocals if vocals.exists() else separated / "source_audio.wav"
        if not audio_path.exists():
            raise NonRetryableError("chưa có audio — chạy stage separate trước")

        model = resolve_model_for_env()
        result = transcribe(
            audio_path, model=model, language=to_language_code(source.source_locale)
        )

        self._clear_previous(ctx, source.id)

        transcript = Transcript(
            source_video_id=source.id,
            locale=source.source_locale or result.language,
            provider="mlx-whisper",
            provider_version=model,
            has_word_timestamps=result.has_word_timestamps,
            full_text=result.full_text,
        )
        ctx.session.add(transcript)
        ctx.session.flush()

        for seg in result.segments:
            ctx.session.add(
                STTSegment(
                    transcript_id=transcript.id,
                    idx=seg.idx,
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    text=seg.text,
                    words=seg.to_json_words(),
                )
            )
        ctx.session.flush()

        word_count = sum(len(s.words) for s in result.segments)
        return StageResult(
            output_ref={
                "transcript_id": transcript.id,
                "language": result.language,
                "segments": len(result.segments),
                "words": word_count,
                "model": model,
                "used_vocals_track": audio_path.name == "vocals.wav",
            },
            usage={"audio_seconds": result.duration_ms / 1000},
            needs_review=not result.segments,
            note="không nhận được lời nói nào" if not result.segments else None,
        )

    def _clear_previous(self, ctx: StageContext, source_id: str) -> None:
        """Idempotent (§11.1): xoá transcript cũ của source này trước khi ghi lại."""
        old = ctx.session.scalars(
            select(Transcript).where(Transcript.source_video_id == source_id)
        ).all()
        for t in old:
            ctx.session.query(STTSegment).filter(
                STTSegment.transcript_id == t.id
            ).delete(synchronize_session=False)
            ctx.session.delete(t)
        ctx.session.flush()
