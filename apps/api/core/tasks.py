"""Task Celery — chỉ gọi lại hàm thuần đã có trong `services/pipeline_runner.py`
(§11.1: đổi cách gọi, không viết lại logic). Trả về dict JSON-safe thay vì
`PipelineReport` thẳng — dataclass lồng `StrEnum` không tự serialize qua
Celery's JSON serializer.

Task đăng ký ở đây chạy trong tiến trình WORKER riêng
(`.venv/bin/python scripts/worker.py`), không phải tiến trình gọi
`.delay()`/`.apply_async()` — mỗi task tự mở session DB của chính nó
(`session_scope()` bên trong `run_for_video`/`resume_job`), không truyền
Session qua ranh giới task (không serialize được, và mỗi worker process có
kết nối DB riêng).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.celery_app import app
from core.orchestrator import PipelineReport
from services.pipeline_runner import resume_job, run_for_video


def _serialize(report: PipelineReport) -> dict[str, Any]:
    return {
        "job_id": report.job_id,
        "locale": report.locale,
        "ok": report.ok,
        "total_ms": report.total_ms,
        "cached_count": report.cached_count,
        "outcomes": [
            {
                "stage": str(o.stage),
                "status": str(o.status),
                "cached": o.cached,
                "duration_ms": o.duration_ms,
                "note": o.note,
            }
            for o in report.outcomes
        ],
    }


@app.task(name="vla.run_for_video")
def run_for_video_task(
    video_path: str,
    locales: list[str],
    *,
    project_name: str = "Demo",
    rights_note: str = "Fixture/demo — dùng cho chạy thử nội bộ.",
    source_locale: str = "en-US",
    translation_provider: str | None = None,
    tts_provider: str | None = None,
    rerun_from: str | None = None,
) -> dict[str, Any]:
    result = run_for_video(
        Path(video_path), locales,
        project_name=project_name, rights_note=rights_note, source_locale=source_locale,
        translation_provider=translation_provider, tts_provider=tts_provider,
        rerun_from=rerun_from,
    )
    return {
        "project_id": result.project_id,
        "project_name": result.project_name,
        "source_video_id": result.source_video_id,
        "reports": [_serialize(r) for r in result.reports],
    }


@app.task(name="vla.resume_job")
def resume_job_task(job_id: str) -> dict[str, Any]:
    """Chạy tiếp một job đang NEEDS_REVIEW chờ duyệt approval gate (§11.2) —
    xem `services/pipeline_runner.py::resume_job` và
    `.claude/rules/approval-gates.md`."""
    return _serialize(resume_job(job_id))
