"""FastAPI dev server — xem pipeline chạy trực tiếp trên trình duyệt.

CHỈ để chạy thử cục bộ (localhost). KHÔNG phải dashboard Phase 4 (§19) — đó sẽ
là React/Next.js riêng. Đây là một trang tĩnh + vài endpoint mỏng.

Chạy:
    .venv/bin/uvicorn api.main:app --reload --app-dir apps/api --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes.pipeline import router as pipeline_router

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Tool Reup — Dev Viewer")
app.include_router(pipeline_router)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
