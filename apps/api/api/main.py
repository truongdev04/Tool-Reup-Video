"""FastAPI backend — dev viewer (trang tĩnh) + API cho dashboard Phase 4 (§19).

`pipeline_router` (`api/routes/pipeline.py`) là dev viewer: CHỈ để chạy thử
cục bộ, trang tĩnh HTML/JS. `dashboard_router` (`api/routes/dashboard.py`) là
API thật cho dashboard Next.js ở `apps/web` (§19) — gọi qua CORS vì chạy
khác port (`localhost:3000` mặc định của `next dev`).

Chạy:
    .venv/bin/uvicorn api.main:app --reload --app-dir apps/api --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes.dashboard import router as dashboard_router
from api.routes.pipeline import router as pipeline_router
from api.routes.publishing import router as publishing_router

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Tool Reup — API")
app.add_middleware(
    CORSMiddleware,
    # Dev only: dashboard Next.js (apps/web) chạy trên port khác localhost.
    # Chưa deploy thật nên chưa cần chốt domain production ở đây (§19).
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(pipeline_router)
app.include_router(dashboard_router)
app.include_router(publishing_router)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
