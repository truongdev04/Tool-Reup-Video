"""Checksum nguồn và cache key.

Cache key PHẢI gồm provider version (docs §16): nếu provider đổi model mà key
không đổi thì cache trả về kết quả của model khác — lỗi rất khó truy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_CHUNK = 1024 * 1024


def file_checksum(path: Path) -> str:
    """SHA-256 của file, đọc theo chunk để không nạp cả video vào RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(payload: Any) -> str:
    """JSON ổn định: sort key, không khoảng trắng thừa — để cùng input ra cùng hash."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def stage_input_hash(
    *,
    stage: str,
    source_checksum: str,
    config_version: str,
    provider: str | None = None,
    provider_version: str | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    """Cache key cho một lần chạy stage (docs §16).

    Gồm: source checksum + stage + provider + provider version + config version
    + tham số. Thiếu bất kỳ thành phần nào cũng dẫn tới cache trả sai kết quả.
    """
    return hashlib.sha256(
        _canonical(
            {
                "stage": stage,
                "source": source_checksum,
                "provider": provider,
                "provider_version": provider_version,
                "config_version": config_version,
                "params": params or {},
            }
        ).encode()
    ).hexdigest()


def output_digest(output_ref: dict[str, Any] | None) -> str:
    """Digest nội dung output của một stage.

    Dùng để nối cache key giữa các stage: cache key của stage sau phụ thuộc
    output của stage trước (§16). Nhờ nối theo nội dung, chạy lại upstream mà
    kết quả không đổi thì downstream vẫn dùng được cache.
    """
    return hashlib.sha256(_canonical(output_ref or {}).encode()).hexdigest()[:32]
