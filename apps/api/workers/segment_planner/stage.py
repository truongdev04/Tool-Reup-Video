"""Stage `segment_plan` — docs §5, §6.6.

Đọc `stt_segments` (tầng 1), ghi `translation_units` (tầng 2) và
`segment_links` (mapping N:M giữa hai tầng).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import StageName
from db.models import (
    STTSegment,
    SegmentLink,
    SourceVideo,
    Transcript,
    TranslationUnit,
)
from services.presets import load_locale
from workers.segment_planner.planner import RawSegment, plan


class SegmentPlanStage(Stage):
    name = StageName.SEGMENT_PLAN

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Kết quả phụ thuộc cả locale nguồn lẫn locale đích: budget ký tự tính
        theo tốc độ đọc của ngôn ngữ đích (§7.2)."""
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        return {
            "locale": ctx.locale,
            "source_locale": source.source_locale if source else None,
        }

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

        if not transcript.has_word_timestamps:
            raise NonRetryableError(
                "transcript thiếu word-level timestamp. Duration Fitting (§7) và "
                "Subtitle (§8) đều phụ thuộc vào nó — đây là bắt buộc, không phải tuỳ chọn"
            )

        rows = ctx.session.scalars(
            select(STTSegment)
            .where(STTSegment.transcript_id == transcript.id)
            .order_by(STTSegment.idx)
        ).all()
        if not rows:
            raise NonRetryableError("transcript không có segment nào")

        source_preset = load_locale(transcript.locale)
        target_preset = load_locale(ctx.locale)

        segments = [
            RawSegment(
                idx=r.idx, start_ms=r.start_ms, end_ms=r.end_ms,
                text=r.text, speaker=r.speaker_id, words=r.words or [],
            )
            for r in rows
        ]
        planned = plan(segments, source_preset=source_preset, target_preset=target_preset)

        # Idempotent (§11.1): xoá kết quả cũ của chính job này trước khi ghi lại.
        self._clear_previous(ctx)

        by_idx = {r.idx: r for r in rows}
        for unit in planned:
            row = TranslationUnit(
                render_job_id=ctx.job_id,
                idx=unit.idx,
                speaker_id=unit.speaker,
                source_text=unit.text,
                start_ms=unit.start_ms,
                end_ms=unit.end_ms,
                char_budget=unit.char_budget,
                needs_transcreation=unit.needs_transcreation,
            )
            ctx.session.add(row)
            ctx.session.flush()

            for seg_idx in unit.source_segment_idxs:
                ctx.session.add(
                    SegmentLink(
                        from_kind="stt_segment", from_id=by_idx[seg_idx].id,
                        to_kind="translation_unit", to_id=row.id,
                    )
                )
        ctx.session.flush()

        merged_ratio = round(len(rows) / len(planned), 2) if planned else 0
        return StageResult(
            output_ref={
                "transcript_id": transcript.id,
                "stt_segments": len(rows),
                "translation_units": len(planned),
                "merge_ratio": merged_ratio,
                "transcreation_units": sum(1 for u in planned if u.needs_transcreation),
                "total_char_budget": sum(u.char_budget for u in planned),
            },
            usage={"segments_processed": len(rows)},
        )

    def _clear_previous(self, ctx: StageContext) -> None:
        old = ctx.session.scalars(
            select(TranslationUnit).where(TranslationUnit.render_job_id == ctx.job_id)
        ).all()
        for unit in old:
            ctx.session.query(SegmentLink).filter(
                SegmentLink.to_kind == "translation_unit",
                SegmentLink.to_id == unit.id,
            ).delete(synchronize_session=False)
            ctx.session.delete(unit)
        ctx.session.flush()
