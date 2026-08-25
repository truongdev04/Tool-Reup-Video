"""Endpoint Settings cho dashboard Phase 4 (§19) — READ-ONLY.

Tách khỏi `dashboard.py` cùng lý do `publishing.py` đã tách: một mối quan tâm
riêng, đủ để có file riêng.

Phạm vi có chủ ý, quyết định lúc thảo luận thêm tính năng này: CHỈ hiện trạng
thái, KHÔNG cho sửa gì qua UI.

- **API key provider** (`services/providers/`, `services/tts/`): đọc từ biến
  môi trường tại thời điểm gọi, không bao giờ lưu DB (§18.1, xem
  `.claude/rules/providers.md`) — Settings vì vậy chỉ báo "đã cấu hình hay
  chưa" (biến môi trường có/thiếu), KHÔNG có ô nhập key nào, và KHÔNG BAO GIỜ
  trả giá trị key thật ra API.
- **Concurrency**: chưa có cơ chế giới hạn "số job chạy song song tối đa" nào
  trong code (`scripts/worker.py` luôn `--pool=solo`, không đọc field nào cho
  giới hạn này) — không có gì để hiện, cố tình không bịa ra field giả.
- **Retention**: `services/storage.py::RETENTION_DAYS` tồn tại nhưng KHÔNG có
  tiến trình purge nào đọc nó (xem tech-debt.md) — Settings hiện đúng giá trị
  đang cấu hình để biết dự định là gì, không ngụ ý có nút "áp dụng ngay".
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from core.config import get_settings
from services.providers.base import ProviderError
from services.providers.registry import available as translation_available
from services.providers.registry import load_config as load_translation_config
from services.publishing.base import PublishingError
from services.publishing.registry import available as publishing_available
from services.publishing.registry import load_config as load_publishing_config
from services.storage import RETENTION_DAYS
from services.tts.base import TTSError
from services.tts.registry import available as tts_available
from services.tts.registry import load_config as load_tts_config

router = APIRouter(prefix="/api/dashboard")


def _translation_providers() -> list[dict[str, Any]]:
    out = []
    for pid in translation_available():
        try:
            c = load_translation_config(pid)
        except ProviderError:
            continue
        out.append({
            "id": c.id, "name": c.name, "adapter": c.adapter,
            "needs_api_key": c.needs_api_key, "api_key_env": c.api_key_env,
            "is_configured": c.is_configured,
        })
    return out


def _tts_providers() -> list[dict[str, Any]]:
    out = []
    for pid in tts_available():
        try:
            c = load_tts_config(pid)
        except TTSError:
            continue
        out.append({
            "id": c.id, "name": c.name, "adapter": c.adapter,
            "needs_api_key": c.needs_api_key, "api_key_env": c.api_key_env,
            "is_configured": c.is_configured,
        })
    return out


def _publishing_platforms() -> list[dict[str, Any]]:
    out = []
    for pid in publishing_available():
        try:
            c = load_publishing_config(pid)
        except PublishingError:
            continue
        out.append({
            "id": c.id, "name": c.name,
            "needs_oauth_app": c.needs_oauth_app, "is_configured": c.is_configured,
        })
    return out


@router.get("/settings")
def get_settings_status() -> dict[str, Any]:
    settings = get_settings()
    missing_filters = settings.verify_ffmpeg()
    return {
        "config_version": settings.config_version,
        "ffmpeg": {
            "ffmpeg_bin": settings.ffmpeg_bin,
            "ffprobe_bin": settings.ffprobe_bin,
            "ok": not missing_filters,
            "missing": missing_filters,
        },
        "translation_providers": _translation_providers(),
        "tts_providers": _tts_providers(),
        "publishing_platforms": _publishing_platforms(),
        #: `ArtifactKind` là StrEnum nên key JSON đã là chuỗi thường (§17.2).
        "retention_days": {k.value: v for k, v in RETENTION_DAYS.items()},
        "thresholds": {
            "max_cumulative_drift_ms": settings.max_cumulative_drift_ms,
            "tempo_min": settings.tempo_min,
            "tempo_max": settings.tempo_max,
            "min_silence_keep_ms": settings.min_silence_keep_ms,
        },
        "diarization": {
            "model": settings.diarization_model,
            "min_speakers": settings.diarization_min_speakers,
            "max_speakers": settings.diarization_max_speakers,
            #: Chỉ báo có/thiếu — KHÔNG BAO GIỜ trả giá trị token thật.
            "hf_token_configured": bool(os.environ.get("HF_TOKEN")),
        },
        "infra": {
            "database_url": settings.database_url,
            "storage_root": str(settings.storage_root),
            "redis_url": settings.redis_url,
            "token_encryption_key_configured": bool(settings.token_encryption_key),
        },
    }
