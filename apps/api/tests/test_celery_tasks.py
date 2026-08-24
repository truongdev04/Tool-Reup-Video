"""Task Celery (§20, hạ tầng Phase 3) — `core/tasks.py` chỉ gọi lại hàm thuần
đã có (`run_for_video`/`resume_job`), không viết lại logic pipeline (§11.1).

Test bằng `Task.apply()` — chạy đồng bộ trong tiến trình test, KHÔNG cần
redis-server/worker thật (khác `.delay()`/`.apply_async()` vốn cần broker
sống). Monkeypatch thẳng hàm bên dưới để không chạy pipeline thật (chậm,
tốn ffmpeg) — mục tiêu test này là dây nối + serialize, không phải lại test
`run_for_video`/`resume_job` (đã test riêng qua các module khác)."""

from __future__ import annotations

from pathlib import Path

import core.tasks as tasks_module
from core.celery_app import app
from core.orchestrator import PipelineReport, StageOutcome
from core.types import JobStatus, StageName
from services.pipeline_runner import RunResult


def test_celery_app_dung_redis_url_tu_settings():
    from core.config import get_settings

    assert app.conf.broker_url == get_settings().redis_url


def test_run_for_video_task_goi_dung_ham_va_serialize_ket_qua(monkeypatch):
    calls = {}

    def fake_run_for_video(video_path, locales, **kwargs):
        calls["args"] = (video_path, locales, kwargs)
        report = PipelineReport(job_id="job-1", locale=locales[0])
        report.outcomes = [
            StageOutcome(
                stage=StageName.INGEST, status=JobStatus.SUCCEEDED,
                cached=False, duration_ms=5, output_ref={}, note=None,
            ),
        ]
        return RunResult(
            project_id="p1", project_name="P", source_video_id="s1", reports=[report],
        )

    monkeypatch.setattr(tasks_module, "run_for_video", fake_run_for_video)

    payload = tasks_module.run_for_video_task.apply(
        args=("video.mp4", ["es-ES"]), kwargs={"project_name": "P"},
    ).get()

    assert calls["args"][0] == Path("video.mp4"), (
        "task phải tự Path(video_path) trước khi gọi run_for_video (nhận string qua JSON)"
    )
    assert calls["args"][2]["project_name"] == "P"
    assert payload["project_id"] == "p1"
    assert payload["reports"][0]["job_id"] == "job-1"
    assert payload["reports"][0]["outcomes"][0]["stage"] == "ingest", (
        "StrEnum phải serialize thành string thuần qua JSON, không phải repr enum"
    )
    assert payload["reports"][0]["ok"] is True


def test_resume_job_task_goi_dung_ham_va_serialize_ket_qua(monkeypatch):
    def fake_resume_job(job_id):
        report = PipelineReport(job_id=job_id, locale="ja-JP")
        report.outcomes = [
            StageOutcome(
                stage=StageName.TRANSLATE, status=JobStatus.NEEDS_REVIEW,
                cached=False, duration_ms=10, output_ref={}, note="chờ duyệt",
            ),
        ]
        return report

    monkeypatch.setattr(tasks_module, "resume_job", fake_resume_job)

    payload = tasks_module.resume_job_task.apply(args=("job-42",)).get()

    assert payload["job_id"] == "job-42"
    assert payload["outcomes"][0]["status"] == "needs_review"
    assert payload["outcomes"][0]["note"] == "chờ duyệt"
