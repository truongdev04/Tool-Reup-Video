"""Stage `publish` (§6.17, §15, §18.1, §18.3) — workers/publishing/stage.py.

Dùng provider `mock` THẬT (config/publishing/mock.json) — không monkeypatch
network vì mock vốn không gọi ra ngoài, xem services/publishing/adapters.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.stage import NonRetryableError, StageContext
from core.types import ArtifactKind, JobStatus, QCVerdict
from db.models import OutputFile, PlatformAccount, Project, PublishingJob, RenderJob, SourceVideo
from services.crypto import decrypt_token, encrypt_token
from services.publishing.adapters import FAIL_MARKER
from services.publishing.base import PublishingError
from workers.publishing.stage import PublishStage


def _setup(session, storage, *, qc_verdict=QCVerdict.PASS):
    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="es-ES")
    session.add(job)
    session.flush()

    final_path = storage.root / "final.mp4"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(b"fake mp4 bytes")
    final = OutputFile(
        render_job_id=job.id, kind=ArtifactKind.FINAL, storage_path="final.mp4",
        qc_verdict=qc_verdict,
    )
    session.add(final)
    session.flush()

    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="es-ES", storage=storage,
    )
    return ctx, final


def _account(session, *, expires_at=None, is_revoked=False, refresh=True) -> PlatformAccount:
    account = PlatformAccount(
        platform="mock", label="Kênh test",
        access_token_encrypted=encrypt_token("mock-access-abc123"),
        refresh_token_encrypted=encrypt_token("mock-refresh-abc123") if refresh else None,
        expires_at=expires_at, is_revoked=is_revoked,
    )
    session.add(account)
    session.flush()
    return account


def test_khong_cau_hinh_publish_thi_bo_qua_khong_chan_pipeline(session, storage):
    ctx, _ = _setup(session, storage)
    result = PublishStage().run(ctx, {})
    assert result.output_ref["skipped"] is True
    assert result.output_ref["reason"] == "chưa cấu hình publish"
    assert not result.needs_review


def test_qc_khong_pass_thi_khong_publish(session, storage):
    ctx, _ = _setup(session, storage, qc_verdict=QCVerdict.FAIL)
    ctx.presets = {"publish_platform": "mock", "publish_account_id": "irrelevant"}
    result = PublishStage().run(ctx, {})
    assert result.output_ref["reason"] == "qc_not_pass"
    assert result.needs_review, "QC không PASS phải cần người xem lại, không im lặng bỏ qua (§15)"


def test_thieu_tai_khoan_thi_needs_review(session, storage):
    ctx, _ = _setup(session, storage)
    ctx.presets = {"publish_platform": "mock"}
    result = PublishStage().run(ctx, {})
    assert result.output_ref["reason"] == "no_account"
    assert result.needs_review


def test_tai_khoan_da_thu_hoi_thi_needs_review(session, storage):
    ctx, _ = _setup(session, storage)
    account = _account(session, is_revoked=True)
    ctx.presets = {"publish_platform": "mock", "publish_account_id": account.id}
    result = PublishStage().run(ctx, {})
    assert result.output_ref["reason"] == "account_invalid"
    assert result.needs_review


def test_publish_thanh_cong_ghi_publishing_job_va_set_ai_disclosure(session, storage):
    ctx, final = _setup(session, storage)
    account = _account(session)
    final.ai_disclosure = False  # giả lập chưa set, để kiểm publish có tự set lại
    ctx.presets = {
        "publish_platform": "mock", "publish_account_id": account.id,
        "publish_title": "Video test", "publish_hashtags": ["ai", "demo"],
    }

    result = PublishStage().run(ctx, {})

    assert result.output_ref["platform"] == "mock"
    assert result.output_ref["platform_video_id"].startswith("mock-video-")
    jobs = session.query(PublishingJob).all()
    assert len(jobs) == 1
    assert jobs[0].account_ref == account.id
    assert jobs[0].quota_units_used == 1600
    assert final.ai_disclosure is True, "publish phải tự set ai_disclosure (§18.2)"


def test_het_quota_thi_needs_review_va_khong_publish_them(session, storage):
    ctx, final = _setup(session, storage)
    account = _account(session)
    # Giả lập đã dùng hết quota hôm nay (6 lần × 1600 = 9600, còn 400 < 1600).
    now = datetime.now(UTC)
    for _ in range(6):
        session.add(PublishingJob(
            output_file_id=final.id, platform="mock", account_ref=account.id,
            status=JobStatus.SUCCEEDED, published_at=now, quota_units_used=1600,
        ))
    session.flush()
    ctx.presets = {"publish_platform": "mock", "publish_account_id": account.id}

    result = PublishStage().run(ctx, {})

    assert result.output_ref["reason"] == "quota_exceeded"
    assert result.needs_review
    assert session.query(PublishingJob).count() == 6, "không được publish thêm khi đã hết quota"


def test_token_het_han_co_refresh_thi_tu_lam_moi_roi_publish_duoc(session, storage):
    ctx, final = _setup(session, storage)
    expired = datetime.now(UTC) - timedelta(hours=1)
    account = _account(session, expires_at=expired, refresh=True)
    old_access = account.access_token_encrypted
    ctx.presets = {"publish_platform": "mock", "publish_account_id": account.id}

    result = PublishStage().run(ctx, {})

    assert "platform_video_id" in result.output_ref, "phải tự refresh token rồi publish được, không needs_review"
    assert account.access_token_encrypted != old_access, "access token phải được thay bằng token mới"
    assert decrypt_token(account.access_token_encrypted).startswith("mock-access-")
    assert account.expires_at > datetime.now(UTC)


def test_token_het_han_khong_co_refresh_thi_needs_review(session, storage):
    ctx, _ = _setup(session, storage)
    expired = datetime.now(UTC) - timedelta(hours=1)
    account = _account(session, expires_at=expired, refresh=False)
    ctx.presets = {"publish_platform": "mock", "publish_account_id": account.id}

    result = PublishStage().run(ctx, {})

    assert result.output_ref["reason"] == "account_invalid"
    assert result.needs_review


def test_khong_co_output_cuoi_thi_loi_khong_the_retry(session, storage):
    ctx, final = _setup(session, storage)
    session.delete(final)
    session.flush()
    account = _account(session)
    ctx.presets = {"publish_platform": "mock", "publish_account_id": account.id}

    with pytest.raises(NonRetryableError, match="output cuối"):
        PublishStage().run(ctx, {})


def test_publish_that_bai_gia_lap_qua_fail_marker(session, storage):
    ctx, final = _setup(session, storage)
    account = _account(session)
    ctx.presets = {
        "publish_platform": "mock", "publish_account_id": account.id,
        "publish_title": f"Video {FAIL_MARKER}",
    }

    with pytest.raises(PublishingError):
        PublishStage().run(ctx, {})

    assert session.query(PublishingJob).count() == 0, "publish lỗi thì không được ghi PublishingJob"
