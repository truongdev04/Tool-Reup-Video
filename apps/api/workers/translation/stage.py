"""Stage `translate` — docs §6.7.

Dịch theo lô để model thấy được mạch, kèm ngữ cảnh trước/sau. Ghi bản dịch có
version và cờ is_active, phục vụ lineage (§10.4) và partial re-run (§11.3).
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select

from core.hashing import output_digest
from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import StageName
from db.models import ApiUsage, Translation, TranslationUnit
from services.presets import load_locale
from services.providers.base import (
    ProviderError,
    TranslationItem,
    TranslationRequest,
)
from services.providers.registry import ProviderNotFound, get_provider
from workers.translation.prompt import over_budget

#: Số đơn vị gửi trong một lần gọi. Lô lớn thì mạch tốt và rẻ hơn, nhưng model
#: dễ bỏ sót đơn vị và một lần lỗi thì mất cả lô.
DEFAULT_BATCH_SIZE = 12

#: Số đơn vị lân cận đưa vào làm ngữ cảnh (§5).
CONTEXT_UNITS = 2


def _provider_id(ctx: StageContext) -> str:
    """Provider lấy từ preset của job, không hard-code (§2.2)."""
    return (
        ctx.presets.get("translation_provider")
        or os.environ.get("VLA_TRANSLATION_PROVIDER")
        or "mock"
    )


class TranslateStage(Stage):
    name = StageName.TRANSLATE

    def _provider(self, ctx: StageContext):
        pid = _provider_id(ctx)
        try:
            return get_provider(pid)
        except ProviderNotFound as exc:
            raise NonRetryableError(str(exc)) from exc
        except ProviderError as exc:
            raise NonRetryableError(str(exc)) from exc

    @property
    def provider(self) -> str | None:  # type: ignore[override]
        return None  # thay đổi theo job, nên đưa vào cache_params

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Provider và model PHẢI vào cache key: đổi model mà key không đổi thì
        cache trả về bản dịch của model khác (§16)."""
        provider = self._provider(ctx)
        return {
            "locale": ctx.locale,
            "provider": provider.id,
            "provider_version": provider.version,
            "glossary": ctx.presets.get("glossary", {}),
            "style_guide": ctx.presets.get("style_guide"),
        }

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        provider = self._provider(ctx)
        target_preset = load_locale(ctx.locale)

        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        if not units:
            raise NonRetryableError("chưa có translation_units — chạy stage segment_plan trước")

        source_locale = ctx.presets.get("source_locale") or "en-US"
        glossary = ctx.presets.get("glossary", {})
        style_guide = ctx.presets.get("style_guide")

        by_idx = {u.idx: u for u in units}
        translations: dict[int, str] = {}
        total_in = total_out = total_chars = 0
        batch_size = int(ctx.presets.get("translation_batch_size", DEFAULT_BATCH_SIZE))

        for start in range(0, len(units), batch_size):
            batch = units[start : start + batch_size]

            request = TranslationRequest(
                items=[
                    TranslationItem(
                        idx=u.idx,
                        text=u.source_text,
                        char_budget=u.char_budget,
                        needs_transcreation=u.needs_transcreation,
                        speaker=u.speaker_id,
                    )
                    for u in batch
                ],
                source_locale=source_locale,
                target_locale=ctx.locale,
                glossary=glossary,
                style_guide=style_guide,
                context_before=_join(units[max(0, start - CONTEXT_UNITS) : start]),
                context_after=_join(units[start + len(batch) : start + len(batch) + CONTEXT_UNITS]),
            )

            try:
                response = provider.translate(request)
            except ProviderError as exc:
                if not exc.retryable:
                    raise NonRetryableError(str(exc)) from exc
                raise

            translations.update(response.translations)
            total_in += response.usage.tokens_in
            total_out += response.usage.tokens_out
            total_chars += response.usage.characters

        self._deactivate_previous(ctx, [u.id for u in units])

        over = 0
        for idx, text in translations.items():
            unit = by_idx.get(idx)
            if unit is None:
                continue  # model trả idx lạ — bỏ qua, không phá dữ liệu
            if over_budget(text, unit.char_budget):
                over += 1

            version = self._next_version(ctx, unit.id)
            ctx.session.add(
                Translation(
                    translation_unit_id=unit.id,
                    locale=ctx.locale,
                    text=text,
                    version=version,
                    provider=provider.id,
                    provider_version=provider.version,
                    glossary_applied=[k for k in glossary if k in unit.source_text],
                    is_active=True,
                )
            )
            unit.is_dirty = False

        ctx.session.add(
            ApiUsage(
                render_job_id=ctx.job_id,
                stage=StageName.TRANSLATE,
                provider=provider.id,
                model=provider.config.model,
                tokens_in=total_in,
                tokens_out=total_out,
                characters=total_chars,
                cost_usd=_cost(provider, total_in, total_out),
            )
        )
        ctx.session.flush()

        return StageResult(
            output_ref={
                "provider": provider.id,
                "model": provider.config.model,
                "units_translated": len(translations),
                "units_total": len(units),
                "over_budget": over,
                "target_locale": ctx.locale,
                # Digest NỘI DUNG bản dịch, không chỉ số lượng (§16) — thiếu
                # trường này thì dịch lại ra chữ khác nhưng cùng số đơn vị
                # (vd. sửa thuật ngữ, `rerun_from(translate)`) sẽ KHÔNG đổi
                # output_digest, khiến downstream (duration_fit/tts/...) cache
                # hit nhầm bản dịch cũ — đúng kiểu lỗi nghiêm trọng nhất mà
                # caching.md cảnh báo (xuất video với audio cũ, không ai biết).
                "texts_digest": output_digest(
                    {str(idx): text for idx, text in sorted(translations.items())}
                ),
            },
            usage={
                "tokens_in": total_in,
                "tokens_out": total_out,
                "characters": total_chars,
            },
            note=(
                f"{over}/{len(units)} đơn vị vượt budget — Duration Fitting sẽ xử lý (§7.2)"
                if over
                else None
            ),
        )

    def _next_version(self, ctx: StageContext, unit_id: str) -> int:
        latest = ctx.session.scalars(
            select(Translation)
            .where(Translation.translation_unit_id == unit_id, Translation.locale == ctx.locale)
            .order_by(Translation.version.desc())
            .limit(1)
        ).first()
        return (latest.version + 1) if latest else 1

    def _deactivate_previous(self, ctx: StageContext, unit_ids: list[str]) -> None:
        """Giữ bản cũ để truy vết (§10.4), chỉ bỏ cờ is_active — không xoá."""
        rows = ctx.session.scalars(
            select(Translation).where(
                Translation.translation_unit_id.in_(unit_ids),
                Translation.locale == ctx.locale,
                Translation.is_active.is_(True),
            )
        ).all()
        for row in rows:
            row.is_active = False
        ctx.session.flush()


def _join(units: list[TranslationUnit]) -> str | None:
    return " ".join(u.source_text for u in units) if units else None


def _cost(provider, tokens_in: int, tokens_out: int) -> float:
    cfg = provider.config
    if cfg.usd_per_1m_input is None or cfg.usd_per_1m_output is None:
        return 0.0
    return (
        tokens_in / 1_000_000 * cfg.usd_per_1m_input
        + tokens_out / 1_000_000 * cfg.usd_per_1m_output
    )
