"""Stage `compose` — docs §6.14.

Áp logo/watermark lên video gốc. KHÔNG phụ thuộc locale — branding giống nhau
cho mọi bản ngôn ngữ của cùng một video, nên `cache_scope=SOURCE` (§16): chạy
một lần, mọi job của cùng source video dùng chung, giống `separate`/`stt`.

Project chưa có `brand_profile_id` (chưa ai tạo brand thật qua UI — Phase 4)
thì tự sinh một brand PLACEHOLDER bằng logo tổng hợp, để trục
"1 video → nhiều bản có thương hiệu" chạy được đầu-cuối ngay cả khi chưa có
asset thật. `BrandProfile.is_placeholder=True` đánh dấu rõ đây không phải
brand người dùng tạo, để không lẫn khi liệt kê qua dashboard thật sau này.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, CacheScope, StageName
from db.models import BrandProfile, Project, SourceVideo
from services.compose_video import overlay_logo

#: Brand tự sinh dùng chung tên này — idempotent: gọi lại không tạo trùng.
_PLACEHOLDER_BRAND_NAME = "Demo Brand (tự sinh, chưa có asset thật)"


class ComposeStage(Stage):
    name = StageName.COMPOSE
    cache_scope = CacheScope.SOURCE

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        project = ctx.session.get(Project, ctx.project_id)
        if project is None:
            raise NonRetryableError("không tìm thấy project")

        brand = self._resolve_brand(ctx, project)
        if brand.logo_path is None:
            return StageResult(
                output_ref={"skipped": True, "reason": "brand không có logo"},
                note="brand không có logo — bỏ qua composite, render sẽ dùng video gốc",
            )

        logo_path = ctx.storage.root / brand.logo_path
        if not logo_path.exists():
            raise NonRetryableError(f"logo không còn trên đĩa: {logo_path}")

        video_path = ctx.storage.root / source.storage_path
        out_path = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="composed.mp4"
        )

        overlay_logo(
            video_path, logo_path, out_path,
            position=brand.logo_position, opacity=brand.logo_opacity,
            scale_pct=brand.logo_scale_pct,
        )

        return StageResult(
            output_ref={
                "path": ctx.storage.relative(out_path),
                "brand_id": brand.id,
                "brand_name": brand.name,
                "is_placeholder": brand.is_placeholder,
                "position": brand.logo_position,
            },
        )

    def _resolve_brand(self, ctx: StageContext, project: Project) -> BrandProfile:
        """Lấy brand đã gán cho project; chưa có thì tự sinh placeholder.

        Idempotent (§11.1): gọi lại nhiều lần không tạo thêm brand mới, kể cả
        khi project.brand_profile_id đã bị set bởi lần chạy trước.
        """
        if project.brand_profile_id:
            brand = ctx.session.get(BrandProfile, project.brand_profile_id)
            if brand is not None:
                return brand

        existing = ctx.session.scalars(
            select(BrandProfile).where(
                BrandProfile.name == _PLACEHOLDER_BRAND_NAME, BrandProfile.is_placeholder.is_(True)
            )
        ).first()
        if existing is not None:
            project.brand_profile_id = existing.id
            ctx.session.flush()
            return existing

        from tests.fixtures.make_brand_assets import make_demo_logo

        logo_dst = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="demo_logo.png"
        )
        make_demo_logo(logo_dst)

        brand = BrandProfile(
            name=_PLACEHOLDER_BRAND_NAME,
            logo_path=ctx.storage.relative(logo_dst),
            is_placeholder=True,
        )
        ctx.session.add(brand)
        ctx.session.flush()
        project.brand_profile_id = brand.id
        ctx.session.flush()
        return brand
