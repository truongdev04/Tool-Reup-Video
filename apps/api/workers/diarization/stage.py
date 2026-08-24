"""Stage `diarize` — Speaker Diarization (docs §6.5).

Nhận diện nhiều người nói trong `vocals.wav` (Demucs đã tách), gán
`Speaker`/`STTSegment.speaker_id` thật bằng pyannote.audio. Không phụ thuộc
locale nên `cache_scope=SOURCE`, giống `stt` (docs §16) — mọi bản dịch của
cùng một video dùng chung kết quả.

**Bỏ qua CÓ CHỦ Ý** (không phải `NonRetryableError`) khi thiếu
`pyannote.audio`/`HF_TOKEN`: trước khi stage này tồn tại, `diarize` là
`NotImplementedStage` trả `output_ref` rỗng và mọi `STTSegment.speaker_id`
mãi mãi `None` — downstream (`segment_planner`, `translation`, `tts`) đã coi
`speaker=None` là "một speaker duy nhất" từ đó tới giờ. Bắt buộc token mới cho
pipeline chạy được sẽ là một regression so với hành vi hiện tại. Cùng nguyên
tắc "có thể bỏ qua, không chặn pipeline" mà `compose`/`render` áp dụng cho
branding thiếu asset thật (xem compose.md).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.config import get_settings
from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, CacheScope, StageName
from db.models import Speaker, SourceVideo, STTSegment, Transcript
from services.diarization_pyannote import (
    DiarizationUnavailable,
    check_available,
    run_diarization,
)
from workers.diarization.assign import SegmentSpan, assign_speakers, total_speech_ms


class DiarizeStage(Stage):
    name = StageName.DIARIZE
    cache_scope = CacheScope.SOURCE
    provider = "pyannote.audio"

    @property
    def provider_version(self) -> str:  # type: ignore[override]
        return get_settings().diarization_model

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Không phụ thuộc locale — đổi model diarization mới cần chạy lại,
        đổi locale đích thì không (§16)."""
        return {"model": ctx.settings.diarization_model}

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        transcript = ctx.session.scalars(
            select(Transcript)
            .where(Transcript.source_video_id == source.id)
            .order_by(Transcript.created_at.desc())
            .limit(1)
        ).first()
        if transcript is None:
            raise NonRetryableError("chưa có transcript — chạy stage stt trước")

        model = ctx.settings.diarization_model
        try:
            check_available()
        except DiarizationUnavailable as exc:
            self._clear_previous(ctx, source.id, transcript.id)
            return StageResult(
                output_ref={"skipped": True, "reason": str(exc), "model": model},
                note=(
                    f"bỏ qua diarization — {exc}. Toàn bộ video coi như một "
                    "speaker (đúng hành vi trước khi stage này được implement)."
                ),
            )

        segments = ctx.session.scalars(
            select(STTSegment)
            .where(STTSegment.transcript_id == transcript.id)
            .order_by(STTSegment.idx)
        ).all()
        if not segments:
            raise NonRetryableError("transcript không có segment nào")

        # Ưu tiên track vocals đã tách — cùng lựa chọn với stage `stt` (giọng
        # sạch, không lẫn nhạc nền, cho diarization chính xác hơn nhiều).
        separated = ctx.storage.path_for(ArtifactKind.SEPARATED, project_id=ctx.project_id)
        vocals = separated / "vocals.wav"
        audio_path = vocals if vocals.exists() else separated / "source_audio.wav"
        if not audio_path.exists():
            raise NonRetryableError("chưa có audio — chạy stage separate trước")

        turns = run_diarization(
            audio_path,
            model=model,
            min_speakers=ctx.settings.diarization_min_speakers,
            max_speakers=ctx.settings.diarization_max_speakers,
        )

        self._clear_previous(ctx, source.id, transcript.id)

        if not turns:
            return StageResult(
                output_ref={"speakers": 0, "segments_assigned": 0, "model": model},
                note="diarization không phát hiện lượt nói nào",
            )

        totals = total_speech_ms(turns)
        speaker_rows: dict[str, Speaker] = {}
        for label, total_ms in totals.items():
            row = Speaker(source_video_id=source.id, label=label, total_speech_ms=total_ms)
            ctx.session.add(row)
            speaker_rows[label] = row
        ctx.session.flush()

        spans = [SegmentSpan(idx=s.idx, start_ms=s.start_ms, end_ms=s.end_ms) for s in segments]
        assigned = assign_speakers(spans, turns)
        by_idx = {s.idx: s for s in segments}
        for idx, label in assigned.items():
            by_idx[idx].speaker_id = speaker_rows[label].id
        ctx.session.flush()

        return StageResult(
            output_ref={
                "speakers": len(speaker_rows),
                "segments_assigned": len(assigned),
                "segments_total": len(segments),
                "model": model,
            },
            usage={"audio_seconds": sum(t.end_ms - t.start_ms for t in turns) / 1000},
        )

    def _clear_previous(self, ctx: StageContext, source_id: str, transcript_id: str) -> None:
        """Idempotent (§11.1): gỡ `speaker_id` trước rồi mới xoá `Speaker`.

        Thứ tự bắt buộc vì FK: `stt_segments.speaker_id` tham chiếu
        `speakers.id`, xoá `Speaker` trước khi null hoá tham chiếu sẽ vỡ FK.
        Chạy cả khi bỏ qua diarization (thiếu token) để không để lại dữ liệu
        cũ từ một lần chạy trước đó còn token — tránh lệch giữa `note` báo
        "bỏ qua" và DB vẫn còn speaker của lần chạy trước.
        """
        segments = ctx.session.scalars(
            select(STTSegment).where(STTSegment.transcript_id == transcript_id)
        ).all()
        for seg in segments:
            seg.speaker_id = None
        ctx.session.flush()

        old_speakers = ctx.session.scalars(
            select(Speaker).where(Speaker.source_video_id == source_id)
        ).all()
        for sp in old_speakers:
            ctx.session.delete(sp)
        ctx.session.flush()
