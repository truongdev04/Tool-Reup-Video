"""Nạp provider từ `config/providers/*.json`.

Thêm provider mới = thả một file JSON, không phải sửa code (§2.2). Nếu provider
đó dùng API tương thích OpenAI (phần lớn: OpenRouter, 9Router, Groq, DeepSeek,
Together, Ollama, LM Studio, vLLM...) thì chỉ cần đặt `adapter` là
`openai_compatible` rồi khai `base_url` và `model`.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.providers.adapters import ADAPTERS
from services.providers.base import ProviderConfig, ProviderError, TranslationProvider

PROVIDER_ROOT = Path(__file__).resolve().parents[2] / "config" / "providers"


class ProviderNotFound(KeyError):
    pass


def _config_path(provider_id: str) -> Path:
    return PROVIDER_ROOT / f"{provider_id}.json"


def load_config(provider_id: str) -> ProviderConfig:
    path = _config_path(provider_id)
    if not path.exists():
        raise ProviderNotFound(
            f"chưa có provider `{provider_id}`. Đang có: {', '.join(available()) or 'không có'}. "
            f"Thêm file {path}"
        )
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    unknown = set(data) - {f.name for f in ProviderConfig.__dataclass_fields__.values()}
    if unknown:
        raise ProviderError(
            f"provider `{provider_id}` có trường lạ trong config: {sorted(unknown)}",
            retryable=False,
        )
    return ProviderConfig(**data)


def get_provider(provider_id: str) -> TranslationProvider:
    config = load_config(provider_id)
    adapter = ADAPTERS.get(config.adapter)
    if adapter is None:
        raise ProviderError(
            f"provider `{provider_id}` khai adapter `{config.adapter}` không tồn tại. "
            f"Đang hỗ trợ: {', '.join(sorted(ADAPTERS))}",
            retryable=False,
        )
    return adapter(config)


def available() -> list[str]:
    if not PROVIDER_ROOT.exists():
        return []
    return sorted(p.stem for p in PROVIDER_ROOT.glob("*.json"))


def configured() -> list[str]:
    """Provider dùng được ngay: không cần API key, hoặc key đã có trong môi trường."""
    out = []
    for pid in available():
        try:
            if load_config(pid).is_configured:
                out.append(pid)
        except (ProviderError, json.JSONDecodeError):
            continue
    return out
