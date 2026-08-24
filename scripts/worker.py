#!/usr/bin/env python
"""Khởi động Celery worker — hạ tầng Phase 3 (docs §20). Xem
`.claude/rules/infra.md` cho luồng vận hành đầy đủ.

    brew services start redis          # một lần, hoặc `redis-server` chạy tay
    .venv/bin/python scripts/worker.py
    .venv/bin/python scripts/worker.py --pool=prefork --concurrency=2   # forward thẳng cho celery

Mặc định `--pool=solo` (không fork tiến trình con) — BẮT BUỘC, không phải
tuỳ chọn: `stt` dùng `mlx-whisper` (Metal GPU qua MLX). Pool mặc định của
Celery là `prefork`, và Metal KHÔNG sống sót qua `fork()` — context GPU vỡ
ngay sau fork với lỗi `[metal::Device] ... Unable to reach
MTLCompilerService`, khiến `stt` FAIL 100% (đã bắt được lỗi này khi chạy thử
thật qua `--via-celery`, không phải đoán). `solo` chạy task tuần tự ngay
trong tiến trình worker chính — không fork, không song song, nhưng đúng với
mlx. Xem `.claude/rules/infra.md` mục "Giới hạn đã biết".

Tương đương `celery -A core.celery_app worker --loglevel=info --pool=solo`
chạy từ trong `apps/api/`, gọi được từ gốc repo giống mọi script khác trong
`scripts/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(_API))

from core.celery_app import app  # noqa: E402

if __name__ == "__main__":
    argv = ["worker", "--loglevel=info", "--pool=solo", *sys.argv[1:]]
    app.worker_main(argv)
