"""Stage `compose` — docs §6.14.

Áp logo/watermark, CTA, intro/outro lên video gốc theo thứ tự: logo → CTA
(trên video CHÍNH, trước khi nối intro/outro) → nối intro/outro. Lý do đặt
CTA trước bước nối: `duration_ms` cuối cùng của CTA phải tính từ điểm kết
thúc của NỘI DUNG CHÍNH, không phải điểm kết thúc sau khi đã có outro — nối
outro vào trước sẽ đẩy khung hiện CTA lệch sớm hơn dự kiến.

KHÔNG phụ thuộc locale — branding giống nhau cho mọi bản ngôn ngữ của cùng
một video, nên `cache_scope=SOURCE` (§16): chạy một lần, mọi job của cùng
source video dùng chung, giống `separate`/`stt`. CTA cũng KHÔNG dịch theo
locale (quyết định có chủ ý, giữ nguyên kiến trúc này — xem compose.md).

Project chưa có `brand_profile_id` (chưa ai tạo brand thật qua UI — Phase 4)
thì tự sinh một brand PLACEHOLDER (logo + intro + outro + CTA mẫu), để trục
"1 video → nhiều bản có thương hiệu" chạy được đầu-cuối ngay cả khi chưa có
asset thật. `BrandProfile.is_placeholder=True` đánh dấu rõ đây không phải
brand người dùng tạo. Asset placeholder lưu ở `Storage.shared_dir` (dùng
chung MỌI project, không phải per-project) — brand placeholder được TÁI DÙNG
theo tên giữa các project, per-project storage sẽ khiến project B đọc nhầm
file vật lý nằm trong thư mục project A (xem `services/storage.py`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, CacheScope, StageName
from db.models import BrandProfile, Project, SourceVideo
from services.compose_video import concat_clips, overlay_cta, overlay_logo, prepare_clip_for_concat
from services.ffmpeg import probe

#: Brand tự sinh dùng chung tên này — idempotent: gọi lại không tạo trùng.
_PLACEHOLDER_BRAND_NAME = "Demo Brand (tự sinh, chưa có asset thật)"


class ComposeStage(Stage):
    name = StageName.COMPOSE
    cache_scope = CacheScope.SOURCE

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Đổi nội dung brand (logo/CTA/intro/outro) mà cache key không đổi
        thì compose tái dùng composite CŨ (§16). `brand_profile_id` một mình
        không đủ — brand có thể bị sửa TRỰC TIẾP (DB, hoặc API/UI Phase 4 sau
        này) mà không đổi id, nên phải đưa cả nội dung field vào key.

        Gọi `_resolve_brand` (không chỉ đọc `project.brand_profile_id` thô)
        để tự tạo brand placeholder NGAY TẠI ĐÂY nếu chưa có, thay vì để
        `run()` mới tạo: `cache_params` chạy TRƯỚC `run()` kể cả khi sẽ cache
        hit, nên nếu để `run()` mới gán `brand_profile_id`, job locale thứ 2
        (cùng source) sẽ tính `cache_params` RA KẾT QUẢ KHÁC job đầu (before
        vs after brand được tạo) — input_hash lệch, compose chạy lại lần 2
        dù cache_scope=SOURCE lẽ ra chỉ chạy 1 lần. `_resolve_brand` idempotent
        nên gọi ở đây an toàn, và `run()` gọi lại chỉ trúng fast-path có sẵn.
        """
        project = ctx.session.get(Project, ctx.project_id)
        if project is None:
            return {"brand": None}
        brand = self._resolve_brand(ctx, project)
        return {
            "brand_id": brand.id,
            "logo_path": brand.logo_path,
            "logo_position": brand.logo_position,
            "logo_opacity": brand.logo_opacity,
            "logo_scale_pct": brand.logo_scale_pct,
            "intro_path": brand.intro_path,
            "outro_path": brand.outro_path,
            "cta_config": brand.cta_config,
        }

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
        applied: list[str] = []
        current = ctx.storage.root / source.storage_path

        if brand.logo_path:
            logo_path = ctx.storage.root / brand.logo_path
            if not logo_path.exists():
                raise NonRetryableError(f"logo không còn trên đĩa: {logo_path}")
            step = ctx.storage.path_for(
                ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="_step_logo.mp4"
            )
            overlay_logo(
                current, logo_path, step,
                position=brand.logo_position, opacity=brand.logo_opacity,
                scale_pct=brand.logo_scale_pct,
            )
            current = step
            applied.append("logo")

        if brand.cta_config:
            current = self._apply_cta(ctx, brand, current)
            applied.append("cta")

        if brand.intro_path or brand.outro_path:
            current = self._apply_intro_outro(ctx, brand, current)
            applied.append("intro/outro")

        if not applied:
            return StageResult(
                output_ref={"skipped": True, "reason": "brand không có logo/CTA/intro/outro"},
                note="brand trống — bỏ qua composite, render sẽ dùng video gốc",
            )

        final_path = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="composed.mp4"
        )
        if current != final_path:
            current.replace(final_path)

        return StageResult(
            output_ref={
                "path": ctx.storage.relative(final_path),
                "brand_id": brand.id,
                "brand_name": brand.name,
                "is_placeholder": brand.is_placeholder,
                "applied": applied,
            },
        )

    def _apply_cta(self, ctx: StageContext, brand: BrandProfile, video_path):
        """CTA hiện trong `duration_ms` CUỐI của video chính — tính từ chính
        `video_path` truyền vào (đã áp logo nếu có, CHƯA nối intro/outro)."""
        from tests.fixtures.make_brand_assets import DEFAULT_CTA_CONFIG

        cfg = {**DEFAULT_CTA_CONFIG, **brand.cta_config}
        info = probe(video_path)
        duration_ms = int(cfg.get("duration_ms", 3000))
        start_ms = max(0, info.duration_ms - duration_ms)

        step = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="_step_cta.mp4"
        )
        overlay_cta(
            video_path, step,
            text=cfg["text"], fontfile=ctx.settings.fonts_dir / "NotoSans-Regular.ttf",
            start_ms=start_ms, duration_ms=duration_ms,
            position=cfg.get("position", "bottom_center"),
            fontsize_pct=float(cfg.get("fontsize_pct", 4.0)),
            color=cfg.get("color", "white"),
        )
        return step

    def _apply_intro_outro(self, ctx: StageContext, brand: BrandProfile, video_path):
        info = probe(video_path)
        width, height, fps = info.width, info.height, info.fps or 30.0
        if not width or not height:
            raise NonRetryableError(f"không đọc được kích thước video: {video_path}")

        clips = []
        if brand.intro_path:
            intro_src = ctx.storage.root / brand.intro_path
            if not intro_src.exists():
                raise NonRetryableError(f"intro không còn trên đĩa: {intro_src}")
            intro_step = ctx.storage.path_for(
                ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="_step_intro.mp4"
            )
            clips.append(prepare_clip_for_concat(intro_src, intro_step, width=width, height=height, fps=fps))

        # Chuẩn hoá LUÔN clip chính qua cùng filter chain (scale/pad/setsar/
        # fps) dù kích thước danh nghĩa đã khớp — `concat` đòi khớp cả SAR,
        # và clip chính có thể có SAR khác 1:1 mà intro/outro (đã chuẩn hoá
        # setsar=1) không khớp theo nếu bỏ qua bước này (đã gặp lỗi thật).
        main_step = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="_step_main_normalized.mp4"
        )
        clips.append(prepare_clip_for_concat(video_path, main_step, width=width, height=height, fps=fps))

        if brand.outro_path:
            outro_src = ctx.storage.root / brand.outro_path
            if not outro_src.exists():
                raise NonRetryableError(f"outro không còn trên đĩa: {outro_src}")
            outro_step = ctx.storage.path_for(
                ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="_step_outro.mp4"
            )
            clips.append(prepare_clip_for_concat(outro_src, outro_step, width=width, height=height, fps=fps))

        step = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="_step_concat.mp4"
        )
        return concat_clips(clips, step)

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

        from tests.fixtures.make_brand_assets import (
            DEFAULT_CTA_CONFIG,
            make_demo_intro,
            make_demo_logo,
            make_demo_outro,
        )

        shared = ctx.storage.shared_dir("brand_placeholder")
        logo_path = make_demo_logo(shared / "demo_logo.png")
        intro_path = make_demo_intro(shared / "demo_intro.mp4")
        outro_path = make_demo_outro(shared / "demo_outro.mp4")

        brand = BrandProfile(
            name=_PLACEHOLDER_BRAND_NAME,
            logo_path=ctx.storage.relative(logo_path),
            intro_path=ctx.storage.relative(intro_path),
            outro_path=ctx.storage.relative(outro_path),
            cta_config=DEFAULT_CTA_CONFIG,
            is_placeholder=True,
        )
        ctx.session.add(brand)
        ctx.session.flush()
        project.brand_profile_id = brand.id
        ctx.session.flush()
        return brand
