"""Stage `tts` — sinh giọng đọc và ép thời lượng bằng SỐ ĐO THẬT (docs §6.9, §7).

Đây là lượt thứ hai của Duration Fitting. `duration_fit` dự báo từ độ dài text;
ở đây audio đã có thật nên đo được chính xác, và phần lệch còn lại được xử lý
bằng atempo trong ngưỡng an toàn.

Mỗi chunk ghi ra MỘT FILE RIÊNG có địa chỉ — điều kiện bắt buộc để partial
re-run hoạt động (§11.3).
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import FitStrategy, StageName
from db.models import ApiUsage, SegmentTiming, Translation, TranslationUnit, TTSChunk
from services.presets import effective_speech_rate
from services.tts.adapters import apply_tempo
from services.tts.base import SynthesisRequest, TTSError
from services.tts.registry import TTSProviderNotFound, get_tts
from workers.duration_fit.fitter import FitInput, decide
from workers.duration_fit.stage import policy_from, silence_after


def _tts_provider_id(ctx: StageContext) -> str:
    return (
        ctx.presets.get("tts_provider")
        or os.environ.get("VLA_TTS_PROVIDER")
        or "macos_say"
    )


class TTSStage(Stage):
    name = StageName.TTS

    def _provider(self, ctx: StageContext):
        try:
            return get_tts(_tts_provider_id(ctx))
        except (TTSProviderNotFound, TTSError) as exc:
            raise NonRetryableError(str(exc)) from exc

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Giọng và provider PHẢI vào cache key: đổi giọng mà key không đổi thì
        cache trả về audio của giọng cũ (§16)."""
        provider = self._provider(ctx)
        try:
            voice = provider.config.voice_for(ctx.locale)
        except TTSError:
            voice = None
        return {
            "locale": ctx.locale,
            "tts_provider": provider.id,
            "tts_version": provider.version,
            "voice": voice,
        }

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        provider = self._provider(ctx)
        policy = policy_from(ctx)
        rate = effective_speech_rate(ctx.locale, provider.id)

        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        if not units:
            raise NonRetryableError("chưa có translation_units — chạy segment_plan trước")

        self._clear_previous(ctx, [u.id for u in units])

        cumulative = 0
        total_chars = 0
        strategies: dict[str, int] = {}
        needs_review = 0
        tempo_applied = 0

        for i, unit in enumerate(units):
            translation = ctx.session.scalars(
                select(Translation).where(
                    Translation.translation_unit_id == unit.id,
                    Translation.locale == ctx.locale,
                    Translation.is_active.is_(True),
                )
            ).first()
            if translation is None:
                raise NonRetryableError(
                    f"đơn vị {unit.idx} chưa có bản dịch — chạy stage translate trước"
                )

            out_path = ctx.storage.tts_chunk_path(
                project_id=ctx.project_id, job_id=ctx.job_id,
                unit_idx=unit.idx, chunk_idx=0,
            )

            try:
                result = provider.synthesize(
                    SynthesisRequest(
                        text=translation.text, locale=ctx.locale, out_path=out_path
                    )
                )
            except TTSError as exc:
                if not exc.retryable:
                    raise NonRetryableError(str(exc)) from exc
                raise

            total_chars += result.characters

            # Số ĐO THẬT — đây mới là căn cứ đáng tin, khác với dự báo ở
            # stage duration_fit.
            next_start = units[i + 1].start_ms if i + 1 < len(units) else None
            decision = decide(
                FitInput(
                    target_duration_ms=unit.duration_ms,
                    actual_duration_ms=result.duration_ms,
                    available_silence_ms=silence_after(ctx, unit, next_start),
                    has_face=unit.has_face,
                    translate_attempts=policy.max_translate_attempts,
                    cumulative_drift_ms=cumulative,
                ),
                policy=policy,
                speech_rate_cps=rate,
            )

            final_duration = result.duration_ms
            if decision.strategy is FitStrategy.TEMPO_ADJUST:
                final_duration = apply_tempo(out_path, decision.tempo_ratio)
                tempo_applied += 1

            cumulative += decision.drift_ms
            strategies[str(decision.strategy)] = strategies.get(str(decision.strategy), 0) + 1
            if decision.needs_manual_review:
                needs_review += 1

            ctx.session.add(
                TTSChunk(
                    translation_unit_id=unit.id,
                    idx=0,
                    text=translation.text,
                    audio_path=ctx.storage.relative(out_path),
                    duration_ms=final_duration,
                    tempo_ratio=decision.tempo_ratio,
                )
            )

            timing = ctx.session.scalars(
                select(SegmentTiming).where(SegmentTiming.translation_unit_id == unit.id)
            ).first()
            if timing is None:
                timing = SegmentTiming(translation_unit_id=unit.id)
                ctx.session.add(timing)

            timing.target_duration_ms = unit.duration_ms
            timing.actual_duration_ms = final_duration
            timing.fit_strategy = decision.strategy
            timing.tempo_ratio = decision.tempo_ratio
            timing.borrowed_silence_ms = decision.borrow_silence_ms
            timing.drift_ms = decision.drift_ms
            timing.cumulative_drift_ms = cumulative
            timing.needs_manual_review = decision.needs_manual_review

        ctx.session.add(
            ApiUsage(
                render_job_id=ctx.job_id,
                stage=StageName.TTS,
                provider=provider.id,
                model=provider.config.model,
                characters=total_chars,
                audio_seconds=sum(
                    (c.duration_ms or 0) for c in ctx.session.scalars(
                        select(TTSChunk).join(TranslationUnit).where(
                            TranslationUnit.render_job_id == ctx.job_id
                        )
                    ).all()
                ) / 1000,
                cost_usd=provider.estimate_cost_usd(total_chars) or 0.0,
            )
        )
        ctx.session.flush()

        over_budget = abs(cumulative) > policy.max_cumulative_drift_ms
        return StageResult(
            output_ref={
                "provider": provider.id,
                "chunks": len(units),
                "cumulative_drift_ms": cumulative,
                "max_cumulative_drift_ms": policy.max_cumulative_drift_ms,
                "strategies": strategies,
                "tempo_applied": tempo_applied,
                "needs_manual_review": needs_review,
            },
            usage={"characters": total_chars},
            needs_review=needs_review > 0 or over_budget,
            note=self._note(cumulative, policy.max_cumulative_drift_ms, needs_review),
        )

    def _note(self, cumulative: int, budget: int, needs_review: int) -> str | None:
        parts = []
        if abs(cumulative) > budget:
            parts.append(
                f"drift tích luỹ {cumulative}ms vượt ngân sách {budget}ms — "
                f"audio sẽ trôi khỏi hình (§15)"
            )
        if needs_review:
            parts.append(f"{needs_review} đơn vị không ép được, cần người xem lại")
        return "; ".join(parts) or None

    def _clear_previous(self, ctx: StageContext, unit_ids: list[str]) -> None:
        """Idempotent (§11.1)."""
        ctx.session.query(TTSChunk).filter(
            TTSChunk.translation_unit_id.in_(unit_ids)
        ).delete(synchronize_session=False)
        ctx.session.flush()
