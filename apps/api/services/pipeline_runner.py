"""Chạy pipeline cho một video — dùng chung giữa CLI harness và dev server.

Tách khỏi `scripts/run_pipeline.py` để không lặp lại logic tạo project/job giữa
hai nơi gọi (CLI và FastAPI dev viewer).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.orchestrator import Orchestrator, PipelineReport
from core.stage import StageContext
from core.types import PIPELINE_ORDER, StageName
from db.base import create_all, session_scope
from db.models import Project, RenderJob, SourceVideo
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
            # Ghi lại presets của LẦN GỌI NÀY lên chính job — resume_job() cần
            # đọc lại đúng provider đã dùng để tiếp tục pipeline sau khi duyệt
            # gate, không phải fallback về mặc định (§11.2, xem approval-gates.md).
            job.presets = presets
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


def rerun_stages_for_job(job_id: str, stages: tuple[StageName, ...] = PIPELINE_ORDER) -> PipelineReport:
    """Chạy `stages` cho một job ĐÃ TỒN TẠI, dùng `job.presets` đã lưu lúc
    tạo/chạy job lần đầu (`run_for_video`) — KHÔNG phải mặc định của tiến
    trình gọi, nếu không có thể chạy tiếp bằng provider dịch/TTS khác với lần
    chạy gốc mà không ai biết.

    Mặc định `stages=PIPELINE_ORDER` (chạy toàn bộ, cache tự lo phần đã
    xong) — dùng khi cần chạy CHỈ MỘT PHẦN mà không muốn orchestrator tự suy
    ra tập stage cần chạy lại (vd. `services/translation_edit.py` đã tự bump
    cache của TRANSLATE thủ công sau khi sửa inline một câu dịch — gọi
    `Orchestrator.rerun_from(TRANSLATE)` ở đây sẽ ép TRANSLATE chạy lại thật,
    gọi provider dịch lần nữa và GHI ĐÈ mất bản sửa thủ công; truyền thẳng
    `dependents_of(TRANSLATE)` làm `stages` để bỏ qua TRANSLATE, xem
    `.claude/rules/approval-gates.md` cho ví dụ tương tự với `resume_job`).
    """
    create_all()
    storage = Storage()
    with session_scope() as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            raise ValueError(f"không có job {job_id}")
        source = session.get(SourceVideo, job.source_video_id)
        ctx = StageContext(
            session=session, job_id=job.id, project_id=job.project_id,
            source_checksum=source.checksum, locale=job.locale, storage=storage,
            presets=job.presets or {},
        )
        return Orchestrator(ctx).run_pipeline(stages=stages)


def resume_job(job_id: str) -> PipelineReport:
    """Tiếp tục MỘT job đang dừng ở NEEDS_REVIEW chờ duyệt approval gate
    (§11.2) — mọi stage đã chạy trước cổng cache-hit tức thì (§16), pipeline
    chỉ thực sự chạy tiếp từ chỗ dừng. Xem `.claude/rules/approval-gates.md`.
    """
    return rerun_stages_for_job(job_id)
