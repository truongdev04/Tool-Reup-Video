"""Chạy pipeline cho một video — dùng chung giữa CLI harness và dev server.

Tách khỏi `scripts/run_pipeline.py` để không lặp lại logic tạo project/job giữa
hai nơi gọi (CLI và FastAPI dev viewer).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.orchestrator import Orchestrator, PipelineReport
from core.stage import StageContext
from core.types import StageName
from db.base import create_all, session_scope
from db.models import Project, RenderJob
from services.approval_gates import ensure_gates
from services.storage import Storage
from workers.ingest.stage import register_source
from workers.registry import register_all

register_all()


@dataclass
class RunResult:
    project_id: str
    project_name: str
    source_video_id: str
    reports: list[PipelineReport]


def run_for_video(
    video_path: Path,
    locales: list[str],
    *,
    project_name: str = "Demo",
    rights_note: str = "Fixture/demo — dùng cho chạy thử nội bộ.",
    source_locale: str = "en-US",
    translation_provider: str | None = None,
    tts_provider: str | None = None,
    rerun_from: str | None = None,
) -> RunResult:
    """Đăng ký source (nếu chưa có) rồi chạy hoặc chạy lại pipeline cho mỗi locale.

    Idempotent theo checksum (§11.1): gọi lại với cùng file không tạo source
    trùng, chỉ tạo thêm job cho locale mới.
    """
    create_all()
    storage = Storage()

    presets: dict[str, str] = {}
    if translation_provider:
        presets["translation_provider"] = translation_provider
    if tts_provider:
        presets["tts_provider"] = tts_provider

    with session_scope() as session:
        project = session.query(Project).filter_by(name=project_name).one_or_none()
        if project is None:
            project = Project(name=project_name, target_locales=locales)
            session.add(project)
            session.flush()

        source = register_source(
            session, storage, project_id=project.id, file_path=video_path,
            rights_note=rights_note, source_locale=source_locale,
        )

        reports: list[PipelineReport] = []
        for locale in locales:
            job = (
                session.query(RenderJob)
                .filter_by(source_video_id=source.id, locale=locale)
                .one_or_none()
            )
            if job is None:
                job = RenderJob(project_id=project.id, source_video_id=source.id, locale=locale)
                session.add(job)
                session.flush()
            # idempotent (§11.1): an toàn gọi lại kể cả job đã có, chỉ tạo
            # bản ghi cổng còn thiếu — không đụng cổng đã duyệt.
            ensure_gates(session, render_job_id=job.id, config=project.approval_gates)

            ctx = StageContext(
                session=session, job_id=job.id, project_id=project.id,
                source_checksum=source.checksum, locale=locale, storage=storage,
                presets=presets,
            )
            orch = Orchestrator(ctx)

            if rerun_from:
                reports.append(orch.rerun_from(StageName(rerun_from)))
            else:
                reports.append(orch.run_pipeline())

        return RunResult(
            project_id=project.id, project_name=project.name,
            source_video_id=source.id, reports=reports,
        )
