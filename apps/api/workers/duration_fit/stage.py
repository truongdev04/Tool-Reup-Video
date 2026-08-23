"""Stage `duration_fit` — lượt DỰ BÁO của việc ép thời lượng (docs §7).

Việc ép thời lượng chia làm hai lượt vì stage không được gọi stage khác (§11.1):

  duration_fit (ở đây)  — DỰ BÁO thời lượng đọc từ độ dài bản dịch và tốc độ đọc
                          đã hiệu chuẩn, ghi SegmentTiming, tính sẵn rate_scale
                          cho TTS. Rẻ, không gọi API.
  tts                   — sinh audio, ĐO thời lượng thật, áp atempo cho phần dư
                          và cập nhật lại SegmentTiming bằng số thật.

Lượt dự báo chỉ chính xác khi speech_rate_cps đã đo từ chính provider TTS sẽ
dùng — xem `scripts/calibrate_speech_rate.py`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import FitStrategy, StageName
from db.models import SegmentTiming, Translation, TranslationUnit
from services.presets import effective_speech_rate
from workers.duration_fit.fitter import FitInput, FitPolicy, decide


def policy_from(ctx: StageContext) -> FitPolicy:
    """Ngưỡng lấy từ Settings và fitting preset, không hard-code (§2.2, §14)."""
    preset = ctx.presets.get("fitting", {})
    s = ctx.settings
    return FitPolicy(
        tempo_min=preset.get("tempo_min", s.tempo_min),
        tempo_max=preset.get("tempo_max", s.tempo_max),
        min_silence_keep_ms=preset.get("min_silence_keep_ms", s.min_silence_keep_ms),
        tolerance=preset.get("tolerance", 0.10),
        allow_video_stretch=preset.get("allow_video_stretch", True),
        max_translate_attempts=preset.get("max_translate_attempts", 2),
        max_cumulative_drift_ms=preset.get(
            "max_cumulative_drift_ms", s.max_cumulative_drift_ms
        ),
    )


def silence_after(ctx: StageContext, unit: TranslationUnit, next_start_ms: int | None) -> int:
    """Khoảng lặng mượn được ngay sau đơn vị này (§7.2 chiến lược #2).

    Luôn chừa lại `min_silence_keep_ms`: ăn sạch khoảng lặng khiến các câu dính
    liền nhau, nghe còn tệ hơn lệch thời lượng.
    """
    if next_start_ms is None:
        return 0
    gap = next_start_ms - unit.end_ms
    return max(0, gap - ctx.settings.min_silence_keep_ms)


class DurationFitStage(Stage):
    name = StageName.DURATION_FIT

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        return {
            "locale": ctx.locale,
            "tts_provider": ctx.presets.get("tts_provider"),
            "speech_rate": effective_speech_rate(
                ctx.locale, ctx.presets.get("tts_provider")
            ),
            "policy": policy_from(ctx).__dict__,
        }

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        if not units:
            raise NonRetryableError("chưa có translation_units — chạy segment_plan trước")

        rate = effective_speech_rate(ctx.locale, ctx.presets.get("tts_provider"))
        policy = policy_from(ctx)

        cumulative = 0
        strategies: dict[str, int] = {}
        needs_review = 0

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

            predicted = max(1, round(len(translation.text) / rate * 1000))
            next_start = units[i + 1].start_ms if i + 1 < len(units) else None

            decision = decide(
                FitInput(
                    target_duration_ms=unit.duration_ms,
                    actual_duration_ms=predicted,
                    available_silence_ms=silence_after(ctx, unit, next_start),
                    has_face=unit.has_face,
                    # Bản dịch đã được prompt kèm char_budget nên coi như đã dùng
                    # hết lượt dịch lại: lượt này không gọi lại LLM được (§11.1).
                    translate_attempts=policy.max_translate_attempts,
                    cumulative_drift_ms=cumulative,
                ),
                policy=policy,
                speech_rate_cps=rate,
            )

            cumulative += decision.drift_ms
            strategies[str(decision.strategy)] = strategies.get(str(decision.strategy), 0) + 1
            if decision.needs_manual_review:
                needs_review += 1

            timing = ctx.session.scalars(
                select(SegmentTiming).where(SegmentTiming.translation_unit_id == unit.id)
            ).first()
            if timing is None:
                timing = SegmentTiming(translation_unit_id=unit.id)
                ctx.session.add(timing)

            timing.target_duration_ms = unit.duration_ms
            timing.actual_duration_ms = predicted  # dự báo; tts sẽ ghi đè bằng số thật
            timing.fit_strategy = decision.strategy
            timing.tempo_ratio = decision.tempo_ratio
            timing.borrowed_silence_ms = decision.borrow_silence_ms
            timing.drift_ms = decision.drift_ms
            timing.cumulative_drift_ms = cumulative
            timing.needs_manual_review = decision.needs_manual_review

        ctx.session.flush()

        return StageResult(
            output_ref={
                "units": len(units),
                "speech_rate_cps": rate,
                "predicted_cumulative_drift_ms": cumulative,
                "strategies": strategies,
                "needs_manual_review": needs_review,
                "is_prediction": True,
            },
            needs_review=needs_review > 0,
            note=(
                f"{needs_review} đơn vị không ép được bằng dự báo — chờ số đo thật ở stage tts"
                if needs_review
                else None
            ),
        )

