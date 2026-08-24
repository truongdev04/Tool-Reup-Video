"""Celery app — hạ tầng Phase 3 (docs §20): "worker tách tiến trình".

Stage contract (§11.1, xem `.claude/rules/stage-contract.md`) đã tách stage
khỏi cách gọi từ Phase 0 — nên gắn Celery ở đây CHỈ là đổi cách gọi
`services/pipeline_runner.py` (xem `core/tasks.py`), không viết lại
Orchestrator/stage nào. Broker/backend là Redis chạy LOCAL trên máy chạy
worker (`brew install redis`), không phải server từ xa — xem
`.claude/rules/infra.md` cho chi tiết vận hành + giới hạn đã biết.

Chạy thử local (3 tiến trình riêng, đúng tinh thần "worker tách tiến trình"):

    brew services start redis                                    # một lần
    .venv/bin/python scripts/worker.py                            # tiến trình worker
    .venv/bin/python scripts/run_pipeline.py --via-celery          # tiến trình gửi task
"""

from __future__ import annotations

from celery import Celery

from core.config import get_settings

_settings = get_settings()

app = Celery(
    "vla",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["core.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    #: JobStatus/StageName là StrEnum (str subclass) nên tự serialize thành
    #: string JSON bình thường — nhưng PipelineReport/StageOutcome là
    #: dataclass, KHÔNG tự serialize được; core/tasks.py luôn trả dict thuần
    #: (xem `_serialize`), không trả dataclass thẳng qua task boundary.
    result_expires=3600,
    task_track_started=True,
)
