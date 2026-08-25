"""Nạp provider publishing từ `config/publishing/*.json` — cùng mẫu
`services/providers/registry.py`/`services/tts/registry.py` (§2.2)."""

from __future__ import annotations

import json
from pathlib import Path

from services.publishing.adapters import build
from services.publishing.base import PublishingConfig, PublishingError, PublishingProvider

PUBLISHING_ROOT = Path(__file__).resolve().parents[2] / "config" / "publishing"


class PublishingProviderNotFound(KeyError):
    pass


def _config_path(provider_id: str) -> Path:
    return PUBLISHING_ROOT / f"{provider_id}.json"


def load_config(provider_id: str) -> PublishingConfig:
    path = _config_path(provider_id)
    if not path.exists():
        raise PublishingProviderNotFound(
            f"chưa có provider publishing `{provider_id}`. Đang có: "
            f"{', '.join(available()) or 'không có'}. Thêm file {path}"
        )
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    unknown = set(data) - {f.name for f in PublishingConfig.__dataclass_fields__.values()}
    if unknown:
        raise PublishingError(
            f"provider publishing `{provider_id}` có trường lạ trong config: {sorted(unknown)}",
            retryable=False,
        )
    return PublishingConfig(**data)


def get_publishing_provider(provider_id: str) -> PublishingProvider:
    return build(load_config(provider_id))


def available() -> list[str]:
    if not PUBLISHING_ROOT.exists():
        return []
    return sorted(p.stem for p in PUBLISHING_ROOT.glob("*.json"))
