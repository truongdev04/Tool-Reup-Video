"""Adapter cho từng giao thức API.

Chỉ có ba giao thức thật sự khác nhau:

  openai_compatible — OpenAI, OpenRouter, 9Router, Groq, DeepSeek, Together,
                      Ollama, LM Studio, vLLM... Phần lớn thế giới dùng chung
                      endpoint `/chat/completions`, nên THÊM PROVIDER MỚI loại
                      này chỉ cần thả một file JSON vào config/providers/,
                      không phải viết code.
  anthropic         — Claude, endpoint `/v1/messages`, system tách riêng.
  gemini            — Google, endpoint `:generateContent`, cấu trúc khác hẳn.

Prompt và cách parse kết quả dùng chung, nằm ở `translation/prompt.py`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from services.providers.base import (
    ProviderError,
    TranslationProvider,
    TranslationRequest,
    TranslationResponse,
    Usage,
)

#: Mã HTTP nên thử lại: quá tải, rate limit, lỗi tạm thời phía server.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _post(url: str, *, headers: dict[str, str], payload: dict, timeout: float) -> dict:
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"hết thời gian chờ sau {timeout}s: {exc}", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"lỗi kết nối: {exc}", retryable=True) from exc

    if response.status_code >= 400:
        body = response.text[:600]
        raise ProviderError(
            f"HTTP {response.status_code}: {body}",
            retryable=response.status_code in _RETRYABLE_STATUS,
        )
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise ProviderError(f"phản hồi không phải JSON: {response.text[:300]}") from exc


def _parse_translations(content: str, expected: list[int]) -> dict[int, str]:
    """Đọc kết quả dịch từ JSON model trả về.

    Model hay bọc JSON trong ```json ... ``` nên phải gỡ trước. Thiếu đơn vị nào
    là lỗi cứng — dịch thiếu segment mà vẫn cho qua thì video ra sẽ câm một đoạn
    (§15 "không thiếu segment").
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"model không trả JSON hợp lệ: {text[:300]}", retryable=True
        ) from exc

    if isinstance(data, dict) and "translations" in data:
        data = data["translations"]
    if not isinstance(data, list):
        raise ProviderError(f"kỳ vọng danh sách bản dịch, nhận được {type(data).__name__}")

    out: dict[int, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("idx")
        translated = entry.get("text") or entry.get("translation")
        if idx is None or translated is None:
            continue
        out[int(idx)] = str(translated).strip()

    if missing := [i for i in expected if i not in out]:
        raise ProviderError(
            f"thiếu bản dịch cho đơn vị {missing} — dịch thiếu segment sẽ làm "
            f"video câm một đoạn",
            retryable=True,
        )
    return out


class OpenAICompatibleProvider(TranslationProvider):
    """Phủ OpenAI, OpenRouter, 9Router, Groq, DeepSeek, Ollama, LM Studio, vLLM..."""

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        from workers.translation.prompt import build_messages

        cfg = self.config
        system, user = build_messages(request)

        headers = {"Content-Type": "application/json", **cfg.extra_headers}
        if key := cfg.resolve_api_key():
            headers["Authorization"] = f"Bearer {key}"

        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            **cfg.extra_body,
        }

        base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        data = _post(
            f"{base}/chat/completions",
            headers=headers, payload=payload, timeout=cfg.timeout_s,
        )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"phản hồi thiếu nội dung: {str(data)[:300]}") from exc

        raw_usage = data.get("usage") or {}
        return TranslationResponse(
            translations=_parse_translations(content, [i.idx for i in request.items]),
            usage=Usage(
                tokens_in=raw_usage.get("prompt_tokens", 0),
                tokens_out=raw_usage.get("completion_tokens", 0),
                characters=sum(len(i.text) for i in request.items),
            ),
            model=data.get("model", cfg.model),
        )


class AnthropicProvider(TranslationProvider):
    """Claude — `/v1/messages`, system prompt là tham số riêng."""

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        from workers.translation.prompt import build_messages

        cfg = self.config
        system, user = build_messages(request)

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            **cfg.extra_headers,
        }
        if key := cfg.resolve_api_key():
            headers["x-api-key"] = key

        base = (cfg.base_url or "https://api.anthropic.com").rstrip("/")
        data = _post(
            f"{base}/v1/messages",
            headers=headers,
            payload={
                "model": cfg.model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                **cfg.extra_body,
            },
            timeout=cfg.timeout_s,
        )

        blocks = data.get("content") or []
        content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not content:
            raise ProviderError(f"phản hồi thiếu nội dung: {str(data)[:300]}")

        raw_usage = data.get("usage") or {}
        return TranslationResponse(
            translations=_parse_translations(content, [i.idx for i in request.items]),
            usage=Usage(
                tokens_in=raw_usage.get("input_tokens", 0),
                tokens_out=raw_usage.get("output_tokens", 0),
                characters=sum(len(i.text) for i in request.items),
            ),
            model=data.get("model", cfg.model),
        )


class GeminiProvider(TranslationProvider):
    """Google Gemini — `:generateContent`, key truyền qua header."""

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        from workers.translation.prompt import build_messages

        cfg = self.config
        system, user = build_messages(request)

        headers = {"Content-Type": "application/json", **cfg.extra_headers}
        if key := cfg.resolve_api_key():
            headers["x-goog-api-key"] = key

        base = (cfg.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        data = _post(
            f"{base}/models/{cfg.model}:generateContent",
            headers=headers,
            payload={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": cfg.temperature,
                    "maxOutputTokens": cfg.max_tokens,
                    "responseMimeType": "application/json",
                },
                **cfg.extra_body,
            },
            timeout=cfg.timeout_s,
        )

        try:
            parts = data["candidates"][0]["content"]["parts"]
            content = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"phản hồi thiếu nội dung: {str(data)[:300]}") from exc

        raw_usage = data.get("usageMetadata") or {}
        return TranslationResponse(
            translations=_parse_translations(content, [i.idx for i in request.items]),
            usage=Usage(
                tokens_in=raw_usage.get("promptTokenCount", 0),
                tokens_out=raw_usage.get("candidatesTokenCount", 0),
                characters=sum(len(i.text) for i in request.items),
            ),
            model=cfg.model,
        )


class MockProvider(TranslationProvider):
    """Provider giả cho test — không gọi mạng, không tốn tiền.

    Mô phỏng hiện tượng cốt lõi của bài toán: bản dịch DÀI hơn bản gốc, để
    Duration Fitting (§7) có cái mà xử lý trong test.
    """

    #: Hệ số giãn độ dài, xấp xỉ EN -> ES.
    expansion: float = 1.25

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        translations: dict[int, str] = {}
        for item in request.items:
            target_len = int(len(item.text) * self.expansion)
            if item.char_budget:
                # Tôn trọng budget — đúng như một model được prompt tử tế sẽ làm.
                target_len = min(target_len, item.char_budget)
            body = f"[{request.target_locale}] {item.text}"
            translations[item.idx] = (
                body[:target_len] if len(body) > target_len else body.ljust(target_len, ".")
            )

        chars = sum(len(i.text) for i in request.items)
        return TranslationResponse(
            translations=translations,
            usage=Usage(tokens_in=chars // 4, tokens_out=chars // 3, characters=chars),
            model=self.config.model,
        )


ADAPTERS: dict[str, type[TranslationProvider]] = {
    "openai_compatible": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "mock": MockProvider,
}
