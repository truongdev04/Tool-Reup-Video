"""Stage `publish` — docs §6.17, §15, §18.1, §18.3.

Chặn publish khi QC không PASS hoặc tài khoản hết hiệu lực (§15: "chỉ publish
khi QC = PASS và account authorization còn hợp lệ"), và khi hết quota ngày
(§18.3 — nút thắt thật của batch). Thiếu cấu hình publish (project không bật
publishing) thì BỎ QUA, không chặn pipeline — cùng nguyên tắc "thiếu cấu hình
thì bỏ qua" của diarize/compose (xem diarization.md, compose.md); khác các
điều kiện QC/tài khoản/quota ở trên, vốn phải NEEDS_REVIEW để người vận hành
biết mà xử lý, không im lặng bỏ qua.

Mỗi lần publish thành công là MỘT sự kiện lịch sử thật trên nền tảng đích
(video mới, id mới) — không phải artifact có thể tái tạo. Vì vậy KHÔNG có
`_clear_previous` như các stage khác: mỗi lần chạy thành công thêm một dòng
`PublishingJob` mới, giữ nguyên lịch sử (khác hẳn TTSChunk/Translation vốn
ghi đè/deactivate bản cũ).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, JobStatus, QCVerdict, StageName
from db.base import utcnow
from db.models import OutputFile, PlatformAccount, PublishingJob, SourceVideo
from services.crypto import decrypt_token, encrypt_token
from services.publishing.base import PublishingError, PublishRequest
from services.publishing.quota import status_for
from services.publishing.registry import PublishingProviderNotFound, get_publishing_provider, load_config


class PublishStage(Stage):
    name = StageName.PUBLISH

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Đổi platform/account/title/description/hashtags phải bump cache —
        khác thì gọi lại với nội dung khác vẫn bị coi là 'đã publish' rồi bỏ
        qua (§16)."""
        return {
            "locale": ctx.locale,
            "publish_platform": ctx.presets.get("publish_platform"),
            "publish_account_id": ctx.presets.get("publish_account_id"),
            "publish_title": ctx.presets.get("publish_title"),
            "publish_description": ctx.presets.get("publish_description"),
            "publish_hashtags": ctx.presets.get("publish_hashtags"),
        }

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        platform = ctx.presets.get("publish_platform")
        if not platform:
            return StageResult(
                output_ref={"skipped": True, "reason": "chưa cấu hình publish"},
                note="bỏ qua publish — project/job chưa chọn platform (§18.3, không chặn pipeline)",
            )

        final = ctx.session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == ctx.job_id, OutputFile.kind == ArtifactKind.FINAL,
            )
        ).first()
        if final is None:
            raise NonRetryableError("chưa có output cuối (OutputFile FINAL) — chạy stage render trước")

        if final.qc_verdict is not QCVerdict.PASS:
            return StageResult(
                output_ref={"skipped": True, "reason": "qc_not_pass", "qc_verdict": str(final.qc_verdict)},
                needs_review=True,
                note=f"QC chưa PASS (hiện tại: {final.qc_verdict}) — không publish, đúng §15",
            )

        try:
            config = load_config(platform)
        except PublishingProviderNotFound as exc:
            raise NonRetryableError(str(exc)) from exc

        account_id = ctx.presets.get("publish_account_id")
        account = ctx.session.get(PlatformAccount, account_id) if account_id else None
        if account is None:
            return StageResult(
                output_ref={"skipped": True, "reason": "no_account"},
                needs_review=True,
                note=f"chưa chọn tài khoản `{platform}` hợp lệ để publish",
            )

        provider = get_publishing_provider(platform)
        now = utcnow()
        if not account.is_usable_at(now):
            if account.is_revoked or not account.refresh_token_encrypted:
                return StageResult(
                    output_ref={"skipped": True, "reason": "account_invalid", "account_id": account.id},
                    needs_review=True,
                    note=f"tài khoản `{account.label}` đã thu hồi hoặc hết hạn không refresh được — "
                         f"cần kết nối lại (§18.1)",
                )
            # Hết hạn nhưng còn refresh_token — làm mới rồi dùng tiếp (§18.1
            # "cơ chế refresh"), không chặn.
            token_set = provider.refresh(refresh_token=decrypt_token(account.refresh_token_encrypted))
            account.access_token_encrypted = encrypt_token(token_set.access_token)
            if token_set.refresh_token:
                account.refresh_token_encrypted = encrypt_token(token_set.refresh_token)
            account.expires_at = (
                utcnow() if token_set.expires_in_s is None
                else _expires_at(token_set.expires_in_s)
            )
            ctx.session.flush()

        used_today = self._units_used_today(ctx, platform=platform, account_id=account.id)
        quota = status_for(config, used_units_today=used_today)
        if not quota.can_publish_one_more:
            return StageResult(
                output_ref={
                    "skipped": True, "reason": "quota_exceeded",
                    "used_units": quota.used_units, "limit_units": quota.limit_units,
                },
                needs_review=True,
                note=f"hết quota `{platform}` hôm nay ({quota.used_units}/{quota.limit_units} đơn vị, "
                     f"§18.3) — thử lại sau",
            )

        source = ctx.session.get(SourceVideo, self._source_video_id(ctx))
        title = ctx.presets.get("publish_title") or self._default_title(source, ctx.locale)
        request = PublishRequest(
            video_path=ctx.storage.root / final.storage_path,
            title=title,
            description=ctx.presets.get("publish_description") or "",
            hashtags=ctx.presets.get("publish_hashtags") or [],
            ai_disclosure=True,
            access_token=decrypt_token(account.access_token_encrypted),
        )

        try:
            result = provider.publish(request)
        except PublishingError as exc:
            if not exc.retryable:
                raise NonRetryableError(str(exc)) from exc
            raise

        ctx.session.add(PublishingJob(
            output_file_id=final.id, platform=platform, account_ref=account.id,
            status=JobStatus.SUCCEEDED, published_at=utcnow(),
            platform_video_id=result.platform_video_id, metadata_payload=result.raw,
            quota_units_used=config.cost_per_upload_units,
        ))
        final.ai_disclosure = True  # §18.2 — tự set khi publish, dù mặc định đã True.
        ctx.session.flush()

        return StageResult(
            output_ref={
                "platform": platform, "platform_video_id": result.platform_video_id,
                "quota_units_used": config.cost_per_upload_units,
            },
            note=f"đã publish lên `{platform}`: {result.platform_video_id}",
        )

    def _source_video_id(self, ctx: StageContext) -> str:
        from db.models import RenderJob

        job = ctx.session.get(RenderJob, ctx.job_id)
        return job.source_video_id if job else ""

    def _default_title(self, source: SourceVideo | None, locale: str) -> str:
        base = source.filename if source else "video"
        return f"{base} ({locale})"

    def _units_used_today(self, ctx: StageContext, *, platform: str, account_id: str) -> int:
        start_of_day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = ctx.session.scalars(
            select(PublishingJob).where(
                PublishingJob.platform == platform,
                PublishingJob.account_ref == account_id,
                PublishingJob.status == JobStatus.SUCCEEDED,
                PublishingJob.published_at >= start_of_day,
            )
        ).all()
        return sum(r.quota_units_used or 0 for r in rows)


def _expires_at(expires_in_s: int):
    from datetime import timedelta

    return utcnow() + timedelta(seconds=expires_in_s)
