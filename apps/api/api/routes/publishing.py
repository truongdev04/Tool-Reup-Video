"""Endpoint publishing cho dashboard Phase 4 thật (§19, §20 Phase 5).

Tách khỏi `dashboard.py` vì luồng OAuth (authorize/callback/consent) đủ khác
biệt (redirect thật, không phải JSON API thuần) để xứng đáng một file riêng.
Cùng `router.prefix="/api/dashboard"` nên URL nằm chung namespace với
`dashboard.py` — hai router mount song song trong `api/main.py`.

Xem `.claude/rules/publishing.md` cho kiến trúc đầy đủ (provider config-driven,
mock provider để test không cần app OAuth thật, quota manager, vì sao publish
không có `_clear_previous`).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from core.orchestrator import PipelineReport
from core.types import ArtifactKind, JobStatus, StageName
from db.base import session_scope
from db.models import OutputFile, PlatformAccount, PublishingJob, RenderJob
from services.crypto import encrypt_token
from services.pipeline_runner import rerun_stages_for_job
from services.publishing.base import PublishingError
from services.publishing.quota import status_for
from services.publishing.registry import (
    PublishingProviderNotFound,
    available,
    get_publishing_provider,
    load_config,
)

router = APIRouter(prefix="/api/dashboard")

#: URL frontend để redirect về sau khi OAuth xong — dev only, cùng giả định
#: cổng 3000 mặc định của `next dev` như CORS trong api/main.py.
_DASHBOARD_URL = "http://localhost:3000"

#: state param chống CSRF cho luồng OAuth (§18.1) — lưu tạm trong bộ nhớ tiến
#: trình API (KHÔNG phải Celery worker, xem infra.md): đủ dùng cho dev tool
#: một tiến trình, không sống sót qua restart/nhiều worker process. Value là
#: (platform, tạo lúc) — hết hạn sau _STATE_TTL_S.
_oauth_states: dict[str, tuple[str, float]] = {}
_STATE_TTL_S = 600


def _new_state(platform: str) -> str:
    state = uuid.uuid4().hex
    _oauth_states[state] = (platform, time.time())
    return state


def _consume_state(state: str, platform: str) -> None:
    entry = _oauth_states.pop(state, None)
    if entry is None:
        raise HTTPException(400, "state không hợp lệ hoặc đã dùng — thử kết nối lại từ đầu")
    stored_platform, created_at = entry
    if stored_platform != platform or time.time() - created_at > _STATE_TTL_S:
        raise HTTPException(400, "state hết hạn hoặc sai platform — thử kết nối lại từ đầu")


def _quota_summary(session) -> list[dict[str, Any]]:
    """Quota còn lại hôm nay cho mọi account chưa revoke (§18.3) — dùng chung
    giữa `/jobs/{id}/publishing` và `/publishing/quota` (Publishing Calendar)."""
    accounts = session.scalars(select(PlatformAccount).where(~PlatformAccount.is_revoked)).all()
    now = datetime.now(UTC)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for a in accounts:
        try:
            config = load_config(a.platform)
        except PublishingError:
            continue
        used = sum(
            r.quota_units_used or 0
            for r in session.scalars(
                select(PublishingJob).where(
                    PublishingJob.platform == a.platform,
                    PublishingJob.account_ref == a.id,
                    PublishingJob.status == JobStatus.SUCCEEDED,
                    PublishingJob.published_at >= start_of_day,
                )
            ).all()
        )
        s = status_for(config, used_units_today=used)
        out.append({
            "account_id": a.id, "label": a.label, "platform": a.platform,
            "used_units": s.used_units, "limit_units": s.limit_units,
            "remaining_uploads": s.remaining_uploads,
        })
    return out


def _serialize_report(report: PipelineReport) -> dict[str, Any]:
    return {
        "job_id": report.job_id, "locale": report.locale, "ok": report.ok,
        "total_ms": report.total_ms, "cached_count": report.cached_count,
        "outcomes": [
            {
                "stage": str(o.stage), "status": str(o.status), "cached": o.cached,
                "duration_ms": o.duration_ms, "note": o.note,
            }
            for o in report.outcomes
        ],
    }


# ---------------------------------------------------------------------------
# Platforms & accounts
# ---------------------------------------------------------------------------


@router.get("/publishing/platforms")
def list_platforms() -> list[dict[str, Any]]:
    out = []
    for pid in available():
        try:
            config = load_config(pid)
        except PublishingError:
            continue
        out.append({
            "id": config.id, "name": config.name, "needs_oauth_app": config.needs_oauth_app,
            "is_configured": config.is_configured,
            "quota_daily_units": config.quota_daily_units,
            "cost_per_upload_units": config.cost_per_upload_units,
        })
    return out


@router.get("/publishing/accounts")
def list_accounts() -> list[dict[str, Any]]:
    with session_scope() as session:
        accounts = session.scalars(
            select(PlatformAccount).order_by(PlatformAccount.created_at.desc())
        ).all()
        now = datetime.now(UTC)
        return [
            {
                "id": a.id, "platform": a.platform, "label": a.label,
                "scopes": a.scopes, "is_revoked": a.is_revoked,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "usable": a.is_usable_at(now),
                "connected_at": a.created_at.isoformat(),
            }
            for a in accounts
        ]


@router.get("/publishing/history")
def publishing_history(limit: int = 100) -> list[dict[str, Any]]:
    """Lịch sử publish TOÀN CỤC (mọi job) cho Publishing Calendar (§19)."""
    with session_scope() as session:
        rows = session.scalars(
            select(PublishingJob).order_by(PublishingJob.created_at.desc()).limit(limit)
        ).all()
        out = []
        for r in rows:
            final = session.get(OutputFile, r.output_file_id)
            job = session.get(RenderJob, final.render_job_id) if final else None
            out.append({
                "id": r.id, "platform": r.platform, "account_ref": r.account_ref,
                "status": str(r.status), "platform_video_id": r.platform_video_id,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "quota_units_used": r.quota_units_used, "error_message": r.error_message,
                "job_id": job.id if job else None, "locale": job.locale if job else None,
            })
        return out


@router.post("/publishing/accounts/{account_id}/revoke")
def revoke_account(account_id: str) -> dict[str, Any]:
    """Cơ chế revoke (§18.1) — không xoá bản ghi, chỉ tắt để giữ lineage của
    PublishingJob đã dùng account này."""
    with session_scope() as session:
        account = session.get(PlatformAccount, account_id)
        if account is None:
            raise HTTPException(404, "không có account này")
        account.is_revoked = True
        return {"id": account.id, "is_revoked": True}


# ---------------------------------------------------------------------------
# OAuth: authorize -> (consent, chỉ mock) -> callback
# ---------------------------------------------------------------------------


#: state -> label do người dùng đặt cho account sắp kết nối (nhập lúc bấm
#: "Connect", cần sống sót qua vòng redirect authorize -> consent -> callback
#: nên gói theo state, cùng vòng đời/độ tin cậy với _oauth_states).
_pending_labels: dict[str, str] = {}


@router.get("/publishing/authorize")
def authorize(request: Request, platform: str, label: str) -> RedirectResponse:
    try:
        provider = get_publishing_provider(platform)
    except PublishingProviderNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    state = _new_state(platform)
    _pending_labels[state] = label

    redirect_uri = str(request.base_url).rstrip("/") + "/api/dashboard/publishing/callback"
    target = provider.authorize_url(state=state, redirect_uri=redirect_uri)
    if target.startswith("/"):
        target = str(request.base_url).rstrip("/") + target
    return RedirectResponse(target)


@router.get("/publishing/callback")
def callback(request: Request, platform: str, code: str, state: str) -> RedirectResponse:
    _consume_state(state, platform)
    label = _pending_labels.pop(state, platform)

    try:
        provider = get_publishing_provider(platform)
        config = load_config(platform)
    except PublishingProviderNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    redirect_uri = str(request.base_url).rstrip("/") + "/api/dashboard/publishing/callback"
    try:
        token_set = provider.exchange_code(code=code, redirect_uri=redirect_uri)
    except PublishingError as exc:
        raise HTTPException(400, str(exc)) from exc

    expires_at = None
    if token_set.expires_in_s is not None:
        expires_at = datetime.now(UTC) + timedelta(seconds=token_set.expires_in_s)

    with session_scope() as session:
        account = PlatformAccount(
            platform=platform, label=label,
            access_token_encrypted=encrypt_token(token_set.access_token),
            refresh_token_encrypted=(
                encrypt_token(token_set.refresh_token) if token_set.refresh_token else None
            ),
            expires_at=expires_at,
            scopes=config.scope,
        )
        session.add(account)
        session.flush()
        account_id = account.id

    return RedirectResponse(f"{_DASHBOARD_URL}/publish?connected={account_id}")


@router.get("/publishing/mock/consent", response_class=HTMLResponse)
def mock_consent(state: str, redirect_uri: str, platform: str) -> str:
    """Trang 'authorization server' GIẢ — người dùng bấm Cho phép, trình
    duyệt điều hướng thật sự về `redirect_uri` với một `code` giả. Mọi bước
    khác của OAuth (redirect, state, callback, mã hoá token) chạy Y HỆT như
    với nền tảng thật — chỉ có bước NÀY là giả."""
    code = f"mock-{state}"
    allow_url = f"{redirect_uri}?code={code}&state={state}&platform={platform}"
    deny_url = f"{_DASHBOARD_URL}/publish?denied=1"
    return f"""
    <!doctype html>
    <html lang="vi"><head><meta charset="utf-8"><title>Mock OAuth — Tool Reup</title>
    <style>
      body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 80px auto; text-align: center; }}
      button {{ padding: 10px 20px; margin: 8px; border-radius: 6px; border: none; font-size: 14px; cursor: pointer; }}
      .allow {{ background: #0f172a; color: white; }}
      .deny {{ background: #e2e8f0; color: #0f172a; }}
    </style></head>
    <body>
      <h2>Mock Platform</h2>
      <p>Tool Reup đang xin quyền đăng video thay bạn (giả lập — không phải nền tảng thật).</p>
      <button class="allow" onclick="location.href='{allow_url}'">Cho phép</button>
      <button class="deny" onclick="location.href='{deny_url}'">Từ chối</button>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Publish một job + lịch sử
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}/publishing")
def job_publishing(job_id: str) -> dict[str, Any]:
    with session_scope() as session:
        final = session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == job_id, OutputFile.kind == ArtifactKind.FINAL,
            )
        ).first()
        history = []
        if final is not None:
            rows = session.scalars(
                select(PublishingJob)
                .where(PublishingJob.output_file_id == final.id)
                .order_by(PublishingJob.created_at.desc())
            ).all()
            history = [
                {
                    "id": r.id, "platform": r.platform, "account_ref": r.account_ref,
                    "status": str(r.status), "platform_video_id": r.platform_video_id,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                    "quota_units_used": r.quota_units_used, "error_message": r.error_message,
                }
                for r in rows
            ]

        return {"history": history, "quota": _quota_summary(session)}


@router.get("/publishing/quota")
def publishing_quota() -> list[dict[str, Any]]:
    with session_scope() as session:
        return _quota_summary(session)


class PublishBody(BaseModel):
    platform: str
    account_id: str
    title: str
    description: str = ""
    hashtags: list[str] = []


@router.post("/jobs/{job_id}/publish")
def publish_job(job_id: str, body: PublishBody) -> dict[str, Any]:
    with session_scope() as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            raise HTTPException(404, "không có job này")
        job.presets = {
            **(job.presets or {}),
            "publish_platform": body.platform,
            "publish_account_id": body.account_id,
            "publish_title": body.title,
            "publish_description": body.description,
            "publish_hashtags": body.hashtags,
        }

    try:
        report = rerun_stages_for_job(job_id, (StageName.PUBLISH,))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _serialize_report(report)
