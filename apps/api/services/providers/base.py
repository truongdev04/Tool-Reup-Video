"""Hợp đồng chung cho provider LLM — docs §2.2, §6.7, §17.

Không hard-code provider vào source (§2.2). Provider được khai báo bằng file
JSON trong `config/providers/`, nên thêm provider mới không cần sửa code —
xem `registry.py`.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """Lỗi từ phía provider. Có `retryable` để orchestrator biết nên thử lại
    hay dừng luôn (§16)."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class MissingAPIKey(ProviderError):
    def __init__(self, provider_id: str, env_var: str) -> None:
        super().__init__(
            f"provider `{provider_id}` cần API key trong biến môi trường `{env_var}`. "
            f"Đặt biến đó rồi chạy lại, hoặc đổi sang provider chạy local "
            f"(vd. ollama) không cần key.",
            retryable=False,
        )
        self.env_var = env_var


@dataclass(frozen=True)
class ProviderConfig:
    """Khai báo một provider. Nạp từ `config/providers/<id>.json`."""

    id: str
    name: str
    #: Adapter xử lý giao thức: openai_compatible | anthropic | gemini | mock.
    adapter: str
    model: str
    base_url: str | None = None
    #: Tên biến môi trường chứa API key. None = không cần key (provider local).
    api_key_env: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout_s: float = 120.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    #: Giá tham khảo để ước tính chi phí trước khi chạy batch (§17.1).
    #: None = chưa biết giá; dry-run sẽ báo là không ước tính được.
    usd_per_1m_input: float | None = None
    usd_per_1m_output: float | None = None

    def resolve_api_key(self) -> str | None:
        """Đọc API key từ môi trường tại thời điểm gọi.

        Key KHÔNG bao giờ được lưu vào database hay ghi ra log (§18.1).
        """
        if not self.api_key_env:
            return None
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MissingAPIKey(self.id, self.api_key_env)
        return key

    @property
    def needs_api_key(self) -> bool:
        return bool(self.api_key_env)

    @property
    def is_configured(self) -> bool:
        """True khi provider dùng được ngay: không cần key, hoặc key đã có."""
        return not self.api_key_env or bool(os.environ.get(self.api_key_env))


@dataclass
class TranslationItem:
    """Một đơn vị cần dịch, kèm ràng buộc của nó."""

    idx: int
    text: str
    #: Số ký tự mục tiêu để đọc vừa khung hình (§7.2 chiến lược #1).
    char_budget: int | None = None
    #: Hook/CTA — dịch thoáng thay vì dịch sát (§6.7).
    needs_transcreation: bool = False
    speaker: str | None = None


@dataclass
class TranslationRequest:
    items: list[TranslationItem]
    source_locale: str
    target_locale: str
    glossary: dict[str, str] = field(default_factory=dict)
    style_guide: str | None = None
    #: Câu trước/sau khối này, chỉ để làm ngữ cảnh — KHÔNG dịch (§5).
    context_before: str | None = None
    context_after: str | None = None


@dataclass
class Usage:
    """Usage thực tế để tính chi phí (§17)."""

    tokens_in: int = 0
    tokens_out: int = 0
    characters: int = 0

    def cost_usd(self, config: ProviderConfig) -> float | None:
        if config.usd_per_1m_input is None or config.usd_per_1m_output is None:
            return None
        return (
            self.tokens_in / 1_000_000 * config.usd_per_1m_input
            + self.tokens_out / 1_000_000 * config.usd_per_1m_output
        )


@dataclass
class TranslationResponse:
    #: idx của TranslationItem -> bản dịch.
    translations: dict[int, str]
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class TranslationProvider(ABC):
    """Adapter cho một giao thức API cụ thể."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def version(self) -> str:
        """Vào cache key (§16). Đổi model = đổi cache key, nếu không thì cache
        trả về kết quả của model khác."""
        return f"{self.config.adapter}:{self.config.model}"

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResponse:
        raise NotImplementedError

    def estimate_usage(self, request: TranslationRequest) -> Usage:
        """Ước usage TRƯỚC khi gọi, cho dry-run chi phí (§17.1).

        Xấp xỉ 4 ký tự ~ 1 token; đủ dùng để chặn một batch 200 video chạy nhầm,
        không nhằm mục đích kế toán chính xác.
        """
        chars = sum(len(i.text) for i in request.items)
        overhead = 400  # prompt hệ thống, glossary, style guide
        return Usage(
            tokens_in=(chars + overhead) // 4,
            tokens_out=chars // 3,  # bản dịch thường dài hơn bản gốc
            characters=chars,
        )
