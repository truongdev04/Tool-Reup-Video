"""Stage `compose` — docs §6.14. Test phần orchestration (không chỉ các hàm
ffmpeg thuần của `services/compose_video.py`, đã test riêng ở
test_compose_video.py): brand placeholder tự tạo, cache ổn định giữa nhiều
locale, thứ tự logo -> CTA -> intro/outro cho đúng độ dài cuối cùng."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.config import get_settings
from core.stage import StageContext
from core.types import ArtifactKind, CacheScope
from db.models import BrandProfile, Project, RenderJob, SourceVideo
from services.ffmpeg import probe
from workers.compose.stage import ComposeStage


def _make_clip(path: Path, *, duration: float = 2.0) -> Path:
    settings = get_settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=gray:s=320x240:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, capture_output=True, timeout=30,
    )
    return path


def _setup(session, storage, *, duration: float = 2.0):
    project = Project(name="T")
    session.add(project)
    session.flush()

    src_path = storage.path_for(ArtifactKind.SOURCE, project_id=project.id, filename="source.mp4")
    _make_clip(src_path, duration=duration)

    source = SourceVideo(
        project_id=project.id, filename="source.mp4", storage_path=storage.relative(src_path),
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()

    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="en-US")
    session.add(job)
    session.flush()

    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="en-US", storage=storage,
    )
    return ctx, project, source


def test_chua_co_brand_thi_tu_sinh_placeholder_du_logo_cta_intro_outro(session, storage):
    ctx, project, source = _setup(session, storage)

    result = ComposeStage().run(ctx, {})

    assert result.output_ref["is_placeholder"] is True
    assert set(result.output_ref["applied"]) == {"logo", "cta", "intro/outro"}
    brand = session.get(BrandProfile, project.brand_profile_id)
    assert brand is not None
    assert brand.logo_path and brand.intro_path and brand.outro_path and brand.cta_config


def test_composed_mp4_dai_hon_source_dung_bang_intro_cong_outro(session, storage):
    ctx, project, source = _setup(session, storage, duration=2.0)

    ComposeStage().run(ctx, {})

    composed = storage.path_for(ArtifactKind.COMPOSED, project_id=project.id, filename="composed.mp4")
    brand = session.get(BrandProfile, project.brand_profile_id)
    intro_ms = probe(storage.root / brand.intro_path).duration_ms
    outro_ms = probe(storage.root / brand.outro_path).duration_ms
    source_ms = probe(storage.root / source.storage_path).duration_ms

    expected = source_ms + intro_ms + outro_ms
    assert probe(composed).duration_ms == pytest.approx(expected, abs=200)


def test_cache_params_on_dinh_giua_hai_locale_cung_project(session, storage):
    """Compose `cache_scope=SOURCE` — phải cho CÙNG cache_params dù gọi từ
    context của locale nào, kể cả lần gọi ĐẦU TIÊN khi brand placeholder CHƯA
    tồn tại (đã có lỗi thật: brand được tạo TRONG `run()` khiến job locale
    thứ 2 tính `cache_params` ra giá trị khác job đầu, làm compose chạy lại
    dù cache_scope=SOURCE lẽ ra chỉ 1 lần — xem cache_params trong stage.py)."""
    ctx1, project, source = _setup(session, storage)
    job2 = RenderJob(project_id=project.id, source_video_id=source.id, locale="ja-JP")
    session.add(job2)
    session.flush()
    ctx2 = StageContext(
        session=session, job_id=job2.id, project_id=project.id,
        source_checksum=source.checksum, locale="ja-JP", storage=storage,
    )

    assert ComposeStage.cache_scope is CacheScope.SOURCE
    params1 = ComposeStage().cache_params(ctx1)
    params2 = ComposeStage().cache_params(ctx2)
    assert params1 == params2, "cache_params phải giống nhau ngay từ lần gọi đầu tiên (trước khi run())"


def test_khong_co_brand_thi_bo_qua_khong_chan_pipeline(session, storage):
    ctx, project, source = _setup(session, storage)
    empty_brand = BrandProfile(name="Rỗng")
    session.add(empty_brand)
    session.flush()
    project.brand_profile_id = empty_brand.id
    session.flush()

    result = ComposeStage().run(ctx, {})

    assert result.output_ref.get("skipped") is True
    composed = storage.path_for(ArtifactKind.COMPOSED, project_id=project.id, filename="composed.mp4")
    assert not composed.exists()
