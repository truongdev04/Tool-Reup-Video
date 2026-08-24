"""services/branding.py — đọc lại độ dài intro/outro `compose` đã nối (§6.14).

`render` và `qc` đều đọc hàm này để bù offset (audio, phụ đề, ngưỡng thời
lượng) — sai ở đây là cả 3 stage cùng sai theo, nên test riêng, kỹ.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.config import get_settings
from core.stage import StageContext
from db.models import BrandProfile, Project, RenderJob, SourceVideo
from services.branding import resolve_intro_outro_durations


def _make_clip(path: Path, *, duration: float) -> Path:
    settings = get_settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=gray:s=64x64:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, capture_output=True, timeout=30,
    )
    return path


def _ctx_with_brand(session, storage, brand: BrandProfile | None):
    project = Project(name="T")
    session.add(project)
    session.flush()
    if brand is not None:
        session.add(brand)
        session.flush()
        project.brand_profile_id = brand.id
        session.flush()

    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="en-US")
    session.add(job)
    session.flush()

    return StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="en-US", storage=storage,
    )


def test_project_chua_gan_brand_thi_bang_khong(session, storage):
    ctx = _ctx_with_brand(session, storage, None)
    result = resolve_intro_outro_durations(ctx)
    assert result.intro_ms == 0
    assert result.outro_ms == 0
    assert result.total_ms == 0


def test_brand_khong_co_intro_outro_thi_bang_khong(session, storage):
    ctx = _ctx_with_brand(session, storage, BrandProfile(name="B"))
    result = resolve_intro_outro_durations(ctx)
    assert result.total_ms == 0


def test_do_dung_do_dai_that_cua_intro_va_outro(session, storage):
    _make_clip(storage.root / "intro.mp4", duration=1.0)
    _make_clip(storage.root / "outro.mp4", duration=2.0)
    brand = BrandProfile(name="B", intro_path="intro.mp4", outro_path="outro.mp4")

    ctx = _ctx_with_brand(session, storage, brand)
    result = resolve_intro_outro_durations(ctx)

    assert result.intro_ms == pytest.approx(1000, abs=50)
    assert result.outro_ms == pytest.approx(2000, abs=50)
    assert result.total_ms == result.intro_ms + result.outro_ms


def test_file_khong_con_tren_dia_thi_coi_nhu_khong_co_khong_loi(session, storage):
    """Đọc lại quyết định compose đã đưa ra — file bị xoá sau khi compose
    chạy không phải lý do chặn render/qc, coi như không có intro/outro."""
    brand = BrandProfile(name="B", intro_path="khong_ton_tai.mp4")
    ctx = _ctx_with_brand(session, storage, brand)

    result = resolve_intro_outro_durations(ctx)
    assert result.intro_ms == 0
