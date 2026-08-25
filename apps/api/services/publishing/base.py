"""Hợp đồng chung cho provider publishing — docs §6.17, §18.1, §18.3.

Cùng mẫu với provider dịch/TTS (`services/providers/`, `services/tts/`):
khai báo bằng file JSON trong `config/publishing/`, thêm nền tảng mới không
cần sửa code (§2.2). Khác một chỗ: publishing cần OAuth (authorize/exchange/
refresh), không chỉ một API key tĩnh — xem `PublishingProvider`.

Lượt này (§20 Phase 5) chỉ có adapter `mock` — đủ để test toàn bộ luồng OAuth
+ quota + publish THẬT (redirect, callback, mã hoá token, chặn khi QC fail/
hết quota) mà không cần tài khoản YouTube/TikTok/Instagram thật. Thêm nền
tảng thật sau này chỉ cần: 1 file `config/publishing/<id>.json` + 1 adapter
mới trong `adapters.py` — xem `.claude/rules/publishing.md`.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PublishingError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class MissingOAuthCreds(PublishingError):
    def __init__(self, provider_id: str, env_var: str) -> None:
        super().__init__(
            f"provider publishing `{provider_id}` cần OAuth client id/secret trong "
            f"biến môi trường `{env_var}`. Đặt biến đó, hoặc dùng provider `mock` để "
            f"test luồng mà không cần app OAuth thật.",
            retryable=False,
        )


@dataclass(frozen=True)
class PublishingConfig:
    id: str
    name: str
    #: Adapter xử lý giao thức: mock | (nền tảng thật thêm sau, xem docstring module).
    adapter: str
    authorize_url: str = ""
    token_url: str = ""
    api_base_url: str = ""
    client_id_env: str | None = None
    client_secret_env: str | None = None
    scope: list[str] = field(default_factory=list)
    #: §18.3 — hạn mức đơn vị/ngày và chi phí đơn vị mỗi lần đăng. Mặc định
    #: khớp số thật của YouTube Data API (10.000/1.600 ≈ 6 video/ngày/project)
    #: dù adapter đang cấu hình là `mock` — để quota manager được kiểm bằng
    #: số liệu thật, không phải số bịa (xem config/publishing/mock.json).
    quota_daily_units: int = 10_000
    cost_per_upload_units: int = 1_600

    @property
    def needs_oauth_app(self) -> bool:
        return bool(self.client_id_env)

    def resolve_client_id(self) -> str | None:
        if not self.client_id_env:
            return None
        value = os.environ.get(self.client_id_env)
        if not value:
            raise MissingOAuthCreds(self.id, self.client_id_env)
        return value

    def resolve_client_secret(self) -> str | None:
        if not self.client_secret_env:
            return None
        value = os.environ.get(self.client_secret_env)
        if not value:
            raise MissingOAuthCreds(self.id, self.client_secret_env)
        return value

    @property
    def is_configured(self) -> bool:
        return not self.needs_oauth_app or bool(os.environ.get(self.client_id_env or ""))


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in_s: int | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishRequest:
    video_path: Path
    title: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    ai_disclosure: bool = True
    #: Token đã giải mã của account đang dùng — provider không tự đọc DB.
    access_token: str = ""


@dataclass
class PublishResult:
    platform_video_id: str
    raw: dict[str, Any] = field(default_factory=dict)


class PublishingProvider(ABC):
    def __init__(self, config: PublishingConfig) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @abstractmethod
    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """URL người dùng cần mở để cấp quyền (bước 1 của 3-legged OAuth)."""
        raise NotImplementedError

    @abstractmethod
    def exchange_code(self, *, code: str, redirect_uri: str) -> TokenSet:
        """Đổi authorization code lấy access/refresh token (bước 2)."""
        raise NotImplementedError

    @abstractmethod
    def refresh(self, *, refresh_token: str) -> TokenSet:
        """Làm mới access token khi hết hạn (§18.1 'cơ chế refresh')."""
        raise NotImplementedError

    @abstractmethod
    def publish(self, request: PublishRequest) -> PublishResult:
        """Đăng video thật lên nền tảng."""
        raise NotImplementedError
