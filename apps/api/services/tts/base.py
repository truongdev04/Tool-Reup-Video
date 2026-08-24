"""Hợp đồng chung cho provider TTS — docs §6.9.

Cùng mẫu với provider dịch (`services/providers/`): khai báo bằng file JSON
trong `config/tts/`, thêm provider mới không phải sửa code (§2.2).

Ràng buộc quan trọng nhất: mỗi chunk sinh ra MỘT FILE RIÊNG có địa chỉ. Đây là
điều kiện bắt buộc để partial re-run hoạt động — sửa một câu chỉ TTS lại chunk
đó rồi remux, không encode lại cả video (§11.3).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class TTSError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class MissingTTSKey(TTSError):
    def __init__(self, provider_id: str, env_var: str) -> None:
        super().__init__(
            f"provider TTS `{provider_id}` cần API key trong biến môi trường "
            f"`{env_var}`. Đặt biến đó, hoặc đổi sang provider chạy local "
            f"(vd. macos_say) không cần key.",
            retryable=False,
        )


class VoiceNotAvailable(TTSError):
    def __init__(self, provider_id: str, locale: str, available: list[str]) -> None:
        super().__init__(
            f"provider `{provider_id}` không có giọng cho locale `{locale}`. "
            f"Đang có: {', '.join(available) or 'không có'}",
            retryable=False,
        )


@dataclass(frozen=True)
class TTSConfig:
    id: str
    name: str
    #: Adapter xử lý giao thức: macos_say | elevenlabs | openai_tts.
    adapter: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    #: locale -> id giọng của provider. Không hard-code trong source (§2.2).
    voices: dict[str, str] = field(default_factory=dict)
    #: locale -> danh sách giọng PHỤ, dùng cho speaker thứ 2 trở đi khi
    #: `diarize` (§6.5) gán được nhiều người nói cho cùng video. Rỗng = mọi
    #: speaker dùng chung `voices[locale]` như trước khi có diarize — không
    #: phải lỗi, chỉ là chưa cấu hình thêm giọng cho provider này (xem
    #: `workers/tts/voice_assignment.py`).
    speaker_voices: dict[str, list[str]] = field(default_factory=dict)
    #: Tốc độ đọc gốc, provider tự hiểu đơn vị (say dùng words/phút).
    default_rate: float | None = None
    #: locale -> số ký tự đọc được mỗi giây, ĐO THỰC TẾ từ chính provider này.
    #:
    #: Tốc độ đọc phụ thuộc provider chứ không chỉ phụ thuộc ngôn ngữ: cùng
    #: tiếng Tây Ban Nha, `say` ở 175 wpm đọc ~21 cps trong khi giá trị ước
    #: lượng chung của locale preset là 14 cps — lệch hơn 50%, và sai số đó đẩy
    #: thẳng vào drift qua char_budget (§7.2).
    #:
    #: Điền bằng `scripts/calibrate_speech_rate.py`, đừng đoán.
    speech_rate_cps: dict[str, float] = field(default_factory=dict)
    sample_rate: int = 44100
    timeout_s: float = 120.0
    extra_body: dict[str, Any] = field(default_factory=dict)
    usd_per_1m_chars: float | None = None

    def resolve_api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MissingTTSKey(self.id, self.api_key_env)
        return key

    @property
    def needs_api_key(self) -> bool:
        return bool(self.api_key_env)

    @property
    def is_configured(self) -> bool:
        return not self.api_key_env or bool(os.environ.get(self.api_key_env))

    def speech_rate_for(self, locale: str, fallback: float) -> float:
        """Tốc độ đọc đã hiệu chuẩn cho locale này, hoặc `fallback` nếu chưa đo.

        `fallback` nên là `LocalePreset.speech_rate_cps` — con số ước lượng
        chung, dùng tạm cho tới khi có số đo thật.
        """
        if locale in self.speech_rate_cps:
            return self.speech_rate_cps[locale]
        lang = locale.split("-", 1)[0].lower()
        for key, rate in self.speech_rate_cps.items():
            if key.split("-", 1)[0].lower() == lang:
                return rate
        return fallback

    @property
    def calibrated_locales(self) -> list[str]:
        return sorted(self.speech_rate_cps)

    def voice_for(self, locale: str) -> str:
        """Giọng cho locale. Thử khớp đầy đủ trước, rồi khớp theo mã ngôn ngữ."""
        if locale in self.voices:
            return self.voices[locale]
        lang = locale.split("-", 1)[0].lower()
        for key, voice in self.voices.items():
            if key.split("-", 1)[0].lower() == lang:
                return voice
        raise VoiceNotAvailable(self.id, locale, sorted(self.voices))

    def alt_voices_for(self, locale: str) -> list[str]:
        """Giọng PHỤ cho locale (speaker thứ 2 trở đi) — cùng luật khớp với
        `voice_for`: khớp đầy đủ trước, rồi theo mã ngôn ngữ. Rỗng nếu provider
        chưa cấu hình giọng phụ cho locale này (không raise — đây là tuỳ chọn,
        không phải bắt buộc như `voice_for`)."""
        if locale in self.speaker_voices:
            return self.speaker_voices[locale]
        lang = locale.split("-", 1)[0].lower()
        for key, alts in self.speaker_voices.items():
            if key.split("-", 1)[0].lower() == lang:
                return alts
        return []


@dataclass
class SynthesisRequest:
    text: str
    locale: str
    out_path: Path
    voice: str | None = None
    #: Hệ số tốc độ mong muốn (1.0 = bình thường). Duration Fitting dùng để
    #: đặt trước tốc độ thay vì phải atempo sau (§7.2).
    rate_scale: float = 1.0


@dataclass
class SynthesisResult:
    path: Path
    duration_ms: int
    voice: str
    provider: str
    characters: int = 0

    @property
    def is_empty(self) -> bool:
        return self.duration_ms <= 0


class TTSProvider(ABC):
    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def version(self) -> str:
        """Vào cache key (§16) — đổi giọng/model mà key không đổi thì cache trả
        về audio của giọng khác."""
        return f"{self.config.adapter}:{self.config.model or 'default'}"

    @abstractmethod
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """Sinh audio cho MỘT chunk, ghi ra `request.out_path`."""
        raise NotImplementedError

    def estimate_cost_usd(self, characters: int) -> float | None:
        if self.config.usd_per_1m_chars is None:
            return None
        return characters / 1_000_000 * self.config.usd_per_1m_chars
