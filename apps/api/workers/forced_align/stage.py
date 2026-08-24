"""Stage `forced_align` — docs §8.

Chạy STT (mlx-whisper) lại trên chính audio TTS của từng chunk để lấy cấu trúc
thời gian thật (ranh giới đoạn tại khoảng lặng tự nhiên), rồi rải ký tự của bản
dịch — vốn đáng tin hơn text STT nhận dạng được — vào các mốc đó.

Nguyên tắc bất biến (§8.3, §2.9): mọi timestamp phục vụ subtitle phải đến từ
audio SẼ PHÁT, không bao giờ từ audio nguồn. Stage này là nơi hiện thực hoá
nguyên tắc đó.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import StageName
from db.models import TranslationUnit, TTSChunk
from services.presets import to_language_code
from workers.forced_align.aligner import SpeechSpan, char_time_map
from workers.stt.transcriber import resolve_model_for_env, transcribe


class ForcedAlignStage(Stage):
    name = StageName.FORCED_ALIGN
    provider = "mlx-whisper"

    @property
    def provider_version(self) -> str:  # type: ignore[override]
        return resolve_model_for_env()

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        if not units:
            raise NonRetryableError("chưa có translation_units — chạy segment_plan trước")

        model = resolve_model_for_env()
        # Audio TTS đang nói ngôn ngữ ĐÍCH (ctx.locale) — STT phải nhận dạng
        # đúng ngôn ngữ đó, không phải ngôn ngữ nguồn của video gốc.
        lang = to_language_code(ctx.locale)
        aligned = 0
        fallback_uniform = 0

        for unit in units:
            chunk = ctx.session.scalars(
                select(TTSChunk).where(TTSChunk.translation_unit_id == unit.id)
            ).first()
            if chunk is None or not chunk.audio_path:
                raise NonRetryableError(
                    f"đơn vị {unit.idx} chưa có audio — chạy stage tts trước"
                )

            audio_path = ctx.storage.root / chunk.audio_path
            spans: list[SpeechSpan] = []
            try:
                result = transcribe(audio_path, model=model, language=lang)
                spans = [
                    SpeechSpan(s.start_ms, s.end_ms)
                    for s in result.segments
                    if s.end_ms > s.start_ms
                ]
            except Exception:  # noqa: BLE001 — không để 1 chunk lỗi chặn cả job
                pass

            if spans:
                aligned += 1
            else:
                fallback_uniform += 1

            chunk.char_boundaries_ms = char_time_map(
                chunk.text, spans, chunk.duration_ms or 0
            )

        ctx.session.flush()

        return StageResult(
            output_ref={
                "units": len(units),
                "aligned_from_stt_segments": aligned,
                "fallback_uniform": fallback_uniform,
            },
            note=(
                f"{fallback_uniform}/{len(units)} đơn vị không nhận ra tiếng nói "
                f"khi STT lại — dùng rải đều toàn bộ thời lượng"
                if fallback_uniform
                else None
            ),
        )
