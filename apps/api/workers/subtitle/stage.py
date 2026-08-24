"""Stage `subtitle` — docs §6.11, §8.

Nguyên tắc bất biến (§2.9, §8.3): cue LUÔN dựng từ timestamp của
`forced_align` (audio sẽ phát), không bao giờ từ timestamp transcript nguồn.
`from_forced_alignment=True` trên mọi cue là cách QC (§15) kiểm chứng bằng dữ
liệu thay vì bằng mắt.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, StageName
from db.models import SubtitleCue, Translation, TranslationUnit, TTSChunk
from services.presets import load_locale
from workers.subtitle.splitter import split_unit_into_cues
from workers.subtitle.writer import write_srt


class SubtitleStage(Stage):
    name = StageName.SUBTITLE

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        if not units:
            raise NonRetryableError("chưa có translation_units — chạy segment_plan trước")

        preset = load_locale(ctx.locale)
        self._clear_previous(ctx)

        all_cues = []
        overflow_units = 0

        for i, unit in enumerate(units):
            translation = ctx.session.scalars(
                select(Translation).where(
                    Translation.translation_unit_id == unit.id,
                    Translation.locale == ctx.locale,
                    Translation.is_active.is_(True),
                )
            ).first()
            chunk = ctx.session.scalars(
                select(TTSChunk).where(TTSChunk.translation_unit_id == unit.id)
            ).first()
            if translation is None or chunk is None:
                raise NonRetryableError(
                    f"đơn vị {unit.idx} thiếu bản dịch hoặc audio — chạy translate/tts trước"
                )
            if not chunk.char_boundaries_ms:
                raise NonRetryableError(
                    f"đơn vị {unit.idx} chưa có char_boundaries_ms — chạy stage forced_align trước"
                )

            next_unit = units[i + 1] if i + 1 < len(units) else None
            cues = split_unit_into_cues(
                translation.text, chunk.char_boundaries_ms, unit.start_ms, preset,
                display_end_limit_ms=next_unit.start_ms if next_unit else None,
            )
            for cue in cues:
                if cue.cps > preset.cps_max * 1.5:
                    overflow_units += 1
            all_cues.extend(cues)

        for idx, cue in enumerate(all_cues):
            ctx.session.add(
                SubtitleCue(
                    render_job_id=ctx.job_id, idx=idx,
                    start_ms=cue.start_ms, end_ms=cue.end_ms,
                    lines=cue.lines, cps=cue.cps,
                    from_forced_alignment=True,
                )
            )
        ctx.session.flush()

        srt_path = ctx.storage.path_for(
            ArtifactKind.SUBTITLE, project_id=ctx.project_id, job_id=ctx.job_id,
            filename=f"{ctx.locale}.srt",
        )
        write_srt(all_cues, srt_path)

        return StageResult(
            output_ref={
                "cues": len(all_cues),
                "srt_path": ctx.storage.relative(srt_path),
                "overflow_cps_severely": overflow_units,
            },
            needs_review=overflow_units > 0,
            note=(
                f"{overflow_units} cue vượt xa cps_max dù đã cố tách — câu quá dài hoặc "
                f"không có chỗ tách hợp lý"
                if overflow_units
                else None
            ),
        )

    def _clear_previous(self, ctx: StageContext) -> None:
        """Idempotent (§11.1)."""
        ctx.session.query(SubtitleCue).filter(
            SubtitleCue.render_job_id == ctx.job_id
        ).delete(synchronize_session=False)
        ctx.session.flush()
