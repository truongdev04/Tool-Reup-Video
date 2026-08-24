"""Endpoint cho dashboard Phase 4 THẬT (§19) — Next.js app riêng ở `apps/web`,
gọi qua CORS (`api/main.py`). KHÁC `api/routes/pipeline.py` (dev viewer, chỉ
để debug pipeline cục bộ trên trang tĩnh HTML/JS) — hai router phục vụ hai
mục đích khác nhau, cố ý không gộp.

Lượt này (§19, "vòng vận hành lõi"): Projects, Video Workspace (xem + sửa
inline translation, drift timeline, QC, approval gate), Batch Queue.
Publishing Calendar và Settings để lượt sau.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from core.orchestrator import PipelineReport, dependents_of
from core.types import PIPELINE_ORDER, ApprovalGate, ArtifactKind, StageName
from db.base import session_scope
from db.models import (
    ApprovalGateRecord,
    OutputFile,
    Project,
    RenderJob,
    SegmentTiming,
    SourceVideo,
    StageRun,
    Translation,
    TranslationUnit,
    TTSChunk,
)
from services.approval_gates import approve as approve_gate
from services.pipeline_runner import rerun_stages_for_job, resume_job
from services.storage import Storage
from services.translation_edit import edit_unit_translation

router = APIRouter(prefix="/api/dashboard")

#: Stage nào chạy lại khi sửa inline một translation_unit — TRANSLATE bị loại
#: khỏi tập này có chủ ý (xem services/translation_edit.py): bản dịch đã được
#: sửa thủ công, gọi lại TRANSLATE sẽ ép chạy provider dịch lần nữa và GHI ĐÈ
#: mất bản sửa.
_RERUN_AFTER_TRANSLATION_EDIT = tuple(
    s for s in PIPELINE_ORDER if s in dependents_of(StageName.TRANSLATE)
)


def _serialize_report(report: PipelineReport) -> dict[str, Any]:
    return {
        "job_id": report.job_id,
        "locale": report.locale,
        "ok": report.ok,
        "total_ms": report.total_ms,
        "cached_count": report.cached_count,
        "outcomes": [
            {
                "stage": str(o.stage), "status": str(o.status), "cached": o.cached,
                "duration_ms": o.duration_ms, "note": o.note,
            }
            for o in report.outcomes
        ],
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    with session_scope() as session:
        projects = session.scalars(select(Project).order_by(Project.created_at.desc())).all()
        out = []
        for p in projects:
            source_ids = [
                s.id for s in session.scalars(
                    select(SourceVideo).where(SourceVideo.project_id == p.id)
                ).all()
            ]
            jobs = (
                session.scalars(
                    select(RenderJob).where(RenderJob.source_video_id.in_(source_ids))
                ).all()
                if source_ids else []
            )
            by_status: dict[str, int] = {}
            for j in jobs:
                by_status[str(j.status)] = by_status.get(str(j.status), 0) + 1
            out.append({
                "id": p.id, "name": p.name, "target_locales": p.target_locales,
                "source_video_count": len(source_ids), "job_count": len(jobs),
                "jobs_by_status": by_status, "created_at": p.created_at.isoformat(),
            })
        return out


@router.get("/projects/{project_id}")
def project_detail(project_id: str) -> dict[str, Any]:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "không có project này")

        sources = session.scalars(
            select(SourceVideo).where(SourceVideo.project_id == project_id)
        ).all()
        source_by_id = {s.id: s for s in sources}
        jobs = (
            session.scalars(
                select(RenderJob)
                .where(RenderJob.source_video_id.in_(list(source_by_id)))
                .order_by(RenderJob.created_at.desc())
            ).all()
            if source_by_id else []
        )

        return {
            "id": project.id, "name": project.name, "target_locales": project.target_locales,
            "approval_gates": project.approval_gates,
            "source_videos": [
                {"id": s.id, "filename": s.filename, "source_locale": s.source_locale}
                for s in sources
            ],
            "jobs": [
                {
                    "id": j.id, "locale": j.locale, "status": str(j.status),
                    "current_stage": str(j.current_stage) if j.current_stage else None,
                    "progress": j.progress,
                    "source_filename": (
                        source_by_id[j.source_video_id].filename
                        if j.source_video_id in source_by_id else None
                    ),
                    "created_at": j.created_at.isoformat(),
                }
                for j in jobs
            ],
        }


# ---------------------------------------------------------------------------
# Batch Queue — mọi job, mọi project
# ---------------------------------------------------------------------------


@router.get("/jobs")
def list_jobs(project_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(RenderJob).order_by(RenderJob.created_at.desc()).limit(200)
        if project_id:
            stmt = stmt.where(RenderJob.project_id == project_id)
        if status:
            stmt = stmt.where(RenderJob.status == status)
        jobs = session.scalars(stmt).all()

        out = []
        for j in jobs:
            source = session.get(SourceVideo, j.source_video_id)
            project = session.get(Project, j.project_id)
            out.append({
                "id": j.id, "project_id": j.project_id,
                "project_name": project.name if project else None,
                "locale": j.locale, "status": str(j.status),
                "current_stage": str(j.current_stage) if j.current_stage else None,
                "progress": j.progress, "retry_count": j.retry_count, "priority": j.priority,
                "error_message": j.error_message,
                "source_filename": source.filename if source else None,
                "created_at": j.created_at.isoformat(),
            })
        return out


# ---------------------------------------------------------------------------
# Video Workspace — chi tiết 1 job: transcript/translation/audio/drift/QC/gate
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}")
def job_workspace(job_id: str) -> dict[str, Any]:
    with session_scope() as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            raise HTTPException(404, "không có job này")

        project = session.get(Project, job.project_id)
        source = session.get(SourceVideo, job.source_video_id)

        units = session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == job_id)
            .order_by(TranslationUnit.idx)
        ).all()

        unit_rows = []
        for u in units:
            translation = session.scalars(
                select(Translation).where(
                    Translation.translation_unit_id == u.id,
                    Translation.locale == job.locale,
                    Translation.is_active.is_(True),
                )
            ).first()
            timing = session.scalars(
                select(SegmentTiming).where(SegmentTiming.translation_unit_id == u.id)
            ).first()
            chunk = session.scalars(
                select(TTSChunk).where(TTSChunk.translation_unit_id == u.id)
            ).first()

            unit_rows.append({
                "id": u.id, "idx": u.idx, "start_ms": u.start_ms, "end_ms": u.end_ms,
                "duration_ms": u.duration_ms, "source_text": u.source_text,
                "translated_text": translation.text if translation else None,
                "translation_version": translation.version if translation else None,
                "translation_approved_by": translation.approved_by if translation else None,
                "needs_transcreation": u.needs_transcreation,
                "drift": {
                    "target_duration_ms": timing.target_duration_ms,
                    "actual_duration_ms": timing.actual_duration_ms,
                    "fit_strategy": str(timing.fit_strategy),
                    "tempo_ratio": timing.tempo_ratio,
                    "drift_ms": timing.drift_ms,
                    "cumulative_drift_ms": timing.cumulative_drift_ms,
                    "needs_manual_review": timing.needs_manual_review,
                } if timing else None,
                "audio_url": f"/api/audio/{job_id}/{u.idx}" if chunk and chunk.audio_path else None,
                "audio_duration_ms": chunk.duration_ms if chunk else None,
            })

        gates = session.scalars(
            select(ApprovalGateRecord).where(ApprovalGateRecord.render_job_id == job_id)
        ).all()

        final = session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == job_id, OutputFile.kind == ArtifactKind.FINAL,
            )
        ).first()
        qc_run = session.scalars(
            select(StageRun)
            .where(StageRun.render_job_id == job_id, StageRun.stage == StageName.QC)
            .order_by(StageRun.created_at.desc())
            .limit(1)
        ).first()

        return {
            "id": job.id, "project_id": job.project_id, "project_name": project.name if project else None,
            "locale": job.locale, "status": str(job.status),
            "current_stage": str(job.current_stage) if job.current_stage else None,
            "progress": job.progress, "error_message": job.error_message,
            "source_filename": source.filename if source else None,
            "units": unit_rows,
            "gates": [
                {
                    "gate": str(g.gate), "is_enabled": g.is_enabled,
                    "approved_by": g.approved_by,
                    "approved_at": g.approved_at.isoformat() if g.approved_at else None,
                    "note": g.note,
                }
                for g in gates
            ],
            "qc_verdict": str(final.qc_verdict) if final and final.qc_verdict else None,
            "qc_findings": (qc_run.output_ref or {}).get("findings", []) if qc_run else [],
            "final_video_url": (
                f"/api/video/{job_id}"
                if final and (Storage().root / final.storage_path).exists() else None
            ),
        }


# ---------------------------------------------------------------------------
# Sửa inline một translation_unit (Video Workspace) — §19
# ---------------------------------------------------------------------------


@router.get("/rerun-preview")
def rerun_preview() -> dict[str, Any]:
    """Danh sách stage sẽ chạy lại nếu sửa một câu dịch — hiện cho người dùng
    xem TRƯỚC KHI xác nhận (§19: "hiện rõ sẽ chạy lại gì trước khi xác nhận").
    Tĩnh, không phụ thuộc unit nào cụ thể — dùng chung `dependents_of` mà
    `core/orchestrator.py::rerun_from` cũng dùng cho partial re-run (§11.3).
    """
    return {"stages": [str(s) for s in _RERUN_AFTER_TRANSLATION_EDIT]}


class EditUnitBody(BaseModel):
    locale: str
    text: str
    edited_by: str


@router.patch("/units/{unit_id}")
def edit_unit(unit_id: str, body: EditUnitBody) -> dict[str, Any]:
    with session_scope() as session:
        try:
            translation = edit_unit_translation(
                session, unit_id=unit_id, locale=body.locale, text=body.text,
                edited_by=body.edited_by,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        unit = session.get(TranslationUnit, unit_id)
        return {
            "translation_id": translation.id, "version": translation.version,
            "text": translation.text, "job_id": unit.render_job_id if unit else None,
            "will_rerun": [str(s) for s in _RERUN_AFTER_TRANSLATION_EDIT],
        }


@router.post("/jobs/{job_id}/rerun-downstream")
def rerun_downstream(job_id: str) -> dict[str, Any]:
    """Áp bản sửa inline xuống downstream — KHÔNG chạy lại TRANSLATE (đã sửa
    thủ công, xem `services/translation_edit.py`). Gọi SAU khi người dùng xác
    nhận preview từ `/rerun-preview`."""
    try:
        report = rerun_stages_for_job(job_id, _RERUN_AFTER_TRANSLATION_EDIT)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _serialize_report(report)


# ---------------------------------------------------------------------------
# Approval gates (§11.2) — xem .claude/rules/approval-gates.md
# ---------------------------------------------------------------------------


class ApproveGateBody(BaseModel):
    approved_by: str
    note: str | None = None


@router.post("/jobs/{job_id}/gates/{gate}/approve")
def approve_job_gate(job_id: str, gate: str, body: ApproveGateBody) -> dict[str, Any]:
    with session_scope() as session:
        try:
            record = approve_gate(
                session, render_job_id=job_id, gate=ApprovalGate(gate),
                approved_by=body.approved_by, note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {
            "gate": str(record.gate), "approved_by": record.approved_by,
            "approved_at": record.approved_at.isoformat() if record.approved_at else None,
        }


@router.post("/jobs/{job_id}/resume")
def resume(job_id: str) -> dict[str, Any]:
    """Chạy tiếp một job đang NEEDS_REVIEW chờ duyệt gate — xem
    `services/pipeline_runner.py::resume_job`."""
    try:
        report = resume_job(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _serialize_report(report)
