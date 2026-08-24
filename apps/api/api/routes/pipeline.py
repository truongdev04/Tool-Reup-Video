"""Endpoint cho dev viewer — xem pipeline chạy trên trình duyệt.

CHỈ để chạy thử cục bộ. Không phải dashboard Phase 4 thật (§19, sẽ là
React/Next.js riêng) — đây là lớp mỏng dựng tạm để nhìn kết quả mà không phải
đọc log terminal hay tự query DB.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from core.config import get_settings
from core.types import PIPELINE_ORDER, ArtifactKind, StageName
from db.base import create_all, session_scope
from db.models import (
    OutputFile,
    RenderJob,
    SegmentTiming,
    SourceVideo,
    StageRun,
    Translation,
    TranslationUnit,
    TTSChunk,
)
from services.presets import available_locales
from services.pipeline_runner import run_for_video
from services.providers.registry import available as translation_ids
from services.providers.registry import load_config as load_translation_cfg
from services.storage import Storage
from services.tts.registry import available as tts_ids
from services.tts.registry import load_config as load_tts_cfg

router = APIRouter(prefix="/api")

create_all()

#: Thư mục tạm giữ file người dùng tải lên trong phiên dev này.
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "vla_dev_uploads"
_UPLOAD_DIR.mkdir(exist_ok=True)


def _project_name() -> str:
    return "Dev Viewer"


@router.get("/status")
def status() -> dict:
    settings = get_settings()
    missing = settings.verify_ffmpeg()

    def _describe(ids: list[str], loader) -> list[dict]:
        out = []
        for pid in ids:
            try:
                cfg = loader(pid)
                out.append({"id": pid, "name": cfg.name, "configured": cfg.is_configured})
            except Exception:  # noqa: BLE001 — config lỗi thì báo, không sập trang
                out.append({"id": pid, "name": pid, "configured": False})
        return out

    return {
        "ffmpeg_ok": not missing,
        "ffmpeg_missing": missing,
        "translation_providers": _describe(translation_ids(), load_translation_cfg),
        "tts_providers": _describe(tts_ids(), load_tts_cfg),
        "locales": available_locales(),
        "stages": [str(s) for s in PIPELINE_ORDER],
    }


@router.post("/run")
async def run(
    locales: str = Form(..., description="danh sách locale, cách nhau bởi dấu phẩy"),
    translation_provider: str = Form("mock"),
    tts_provider: str = Form("macos_say"),
    source_locale: str = Form("en-US"),
    use_fixture: bool = Form(True),
    video: UploadFile | None = File(None),
) -> dict:
    locale_list = [loc.strip() for loc in locales.split(",") if loc.strip()]
    if not locale_list:
        raise HTTPException(400, "cần ít nhất một locale")

    if use_fixture or video is None:
        from tests.fixtures.make_fixture import make_sample

        video_path = make_sample()
        rights_note = "Fixture tự sinh bằng ffmpeg lavfi / say — dùng cho chạy thử nội bộ."
    else:
        video_path = _UPLOAD_DIR / f"upload_{video.filename or 'upload.mp4'}"
        with video_path.open("wb") as fh:
            shutil.copyfileobj(video.file, fh)
        rights_note = f"Video người dùng tải lên qua dev viewer: {video.filename}"

    try:
        result = run_for_video(
            video_path, locale_list,
            project_name=_project_name(),
            rights_note=rights_note,
            source_locale=source_locale,
            translation_provider=translation_provider or None,
            tts_provider=tts_provider or None,
        )
    except Exception as exc:  # noqa: BLE001 — trả lỗi rõ ràng cho UI thay vì 500 trắng
        raise HTTPException(500, f"chạy pipeline thất bại: {exc}") from exc

    return {
        "project_id": result.project_id,
        "source_video_id": result.source_video_id,
        "reports": [
            {
                "job_id": r.job_id,
                "locale": r.locale,
                "ok": r.ok,
                "total_ms": r.total_ms,
                "cached_count": r.cached_count,
                "outcomes": [
                    {
                        "stage": str(o.stage),
                        "status": str(o.status),
                        "cached": o.cached,
                        "duration_ms": o.duration_ms,
                        "note": o.note,
                    }
                    for o in r.outcomes
                ],
            }
            for r in result.reports
        ],
    }


@router.get("/jobs")
def list_jobs() -> list[dict]:
    with session_scope() as session:
        jobs = session.scalars(
            select(RenderJob).order_by(RenderJob.created_at.desc()).limit(50)
        ).all()
        out = []
        for job in jobs:
            source = session.get(SourceVideo, job.source_video_id)
            out.append({
                "id": job.id,
                "locale": job.locale,
                "status": str(job.status),
                "current_stage": str(job.current_stage) if job.current_stage else None,
                "progress": job.progress,
                "error_message": job.error_message,
                "source_filename": source.filename if source else None,
                "created_at": job.created_at.isoformat(),
            })
        return out


@router.get("/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    with session_scope() as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            raise HTTPException(404, "không có job này")

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
                "idx": u.idx,
                "start_ms": u.start_ms,
                "end_ms": u.end_ms,
                "duration_ms": u.duration_ms,
                "char_budget": u.char_budget,
                "needs_transcreation": u.needs_transcreation,
                "source_text": u.source_text,
                "translated_text": translation.text if translation else None,
                "translation_version": translation.version if translation else None,
                "timing": {
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
            "id": job.id,
            "locale": job.locale,
            "status": str(job.status),
            "source_filename": source.filename if source else None,
            "units": unit_rows,
            "qc_verdict": str(final.qc_verdict) if final and final.qc_verdict else None,
            "qc_findings": (qc_run.output_ref or {}).get("findings", []) if qc_run else [],
            "final_video_url": (
                f"/api/video/{job_id}" if final and (Storage().root / final.storage_path).exists()
                else None
            ),
        }


@router.get("/audio/{job_id}/{unit_idx}")
def audio(job_id: str, unit_idx: int):
    with session_scope() as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            raise HTTPException(404, "không có job này")

        unit = session.scalars(
            select(TranslationUnit).where(
                TranslationUnit.render_job_id == job_id, TranslationUnit.idx == unit_idx
            )
        ).first()
        if unit is None:
            raise HTTPException(404, "không có đơn vị này")

        chunk = session.scalars(
            select(TTSChunk).where(TTSChunk.translation_unit_id == unit.id)
        ).first()
        if chunk is None or not chunk.audio_path:
            raise HTTPException(404, "chưa có audio cho đơn vị này")

        path = Storage().root / chunk.audio_path
        if not path.exists():
            raise HTTPException(404, "file audio không còn trên đĩa")

        return FileResponse(path, media_type="audio/wav")


@router.get("/video/{job_id}")
def video(job_id: str):
    with session_scope() as session:
        final = session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == job_id, OutputFile.kind == ArtifactKind.FINAL,
            )
        ).first()
        if final is None:
            raise HTTPException(404, "chưa có output cuối cho job này")

        path = Storage().root / final.storage_path
        if not path.exists():
            raise HTTPException(404, "file video không còn trên đĩa")

        return FileResponse(path, media_type="video/mp4")
