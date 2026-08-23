"""Nạp provider TTS từ `config/tts/*.json` — cùng mẫu với provider dịch."""

from __future__ import annotations

import json
from pathlib import Path

from services.tts.adapters import TTS_ADAPTERS
from services.tts.base import TTSConfig, TTSError, TTSProvider

TTS_ROOT = Path(__file__).resolve().parents[2] / "config" / "tts"


class TTSProviderNotFound(KeyError):
    pass


def load_config(provider_id: str) -> TTSConfig:
    path = TTS_ROOT / f"{provider_id}.json"
    if not path.exists():
        raise TTSProviderNotFound(
            f"chưa có provider TTS `{provider_id}`. Đang có: "
            f"{', '.join(available()) or 'không có'}. Thêm file {path}"
        )
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    unknown = set(data) - set(TTSConfig.__dataclass_fields__)
    if unknown:
        raise TTSError(
            f"provider TTS `{provider_id}` có trường lạ: {sorted(unknown)}",
            retryable=False,
        )
    return TTSConfig(**data)


def get_tts(provider_id: str) -> TTSProvider:
    config = load_config(provider_id)
    adapter = TTS_ADAPTERS.get(config.adapter)
    if adapter is None:
        raise TTSError(
            f"provider TTS `{provider_id}` khai adapter `{config.adapter}` không tồn tại. "
            f"Đang hỗ trợ: {', '.join(sorted(TTS_ADAPTERS))}",
            retryable=False,
        )
    return adapter(config)


def available() -> list[str]:
    if not TTS_ROOT.exists():
        return []
    return sorted(p.stem for p in TTS_ROOT.glob("*.json"))


def configured() -> list[str]:
    out = []
    for pid in available():
        try:
            if load_config(pid).is_configured:
                out.append(pid)
        except (TTSError, json.JSONDecodeError):
            continue
    return out
