"""Adapter TTS theo giao thức.

`macos_say` chạy local, miễn phí, không cần API key — đủ để dựng và kiểm chứng
toàn bộ trục tts → forced_align → timeline_assembly → subtitle → render trước
khi chốt provider thương mại (§23 #3).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

from core.config import get_settings
from services.ffmpeg import probe, run_ffmpeg
from services.tts.base import (
    SynthesisRequest,
    SynthesisResult,
    TTSError,
    TTSProvider,
)

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

#: Tốc độ đọc mặc định của `say`, tính bằng từ/phút.
_SAY_BASE_WPM = 175


def _finalize(raw: Path, out_path: Path, *, sample_rate: int) -> int:
    """Chuẩn hoá về WAV mono PCM và trả về thời lượng thật (ms).

    Thời lượng phải ĐO từ file đã sinh, không được ước từ số ký tự — toàn bộ
    Duration Fitting (§7) dựa trên con số này.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(raw),
        "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le",
        str(out_path),
    ])
    return probe(out_path).duration_ms


class MacOSSayProvider(TTSProvider):
    """Dùng lệnh `say` có sẵn của macOS. Local, miễn phí, không cần key."""

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        voice = request.voice or self.config.voice_for(request.locale)

        rate = int((self.config.default_rate or _SAY_BASE_WPM) * request.rate_scale)
        raw = request.out_path.with_suffix(".aiff")
        raw.parent.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                ["say", "-v", voice, "-r", str(rate), "-o", str(raw), request.text],
                check=True, capture_output=True, timeout=self.config.timeout_s,
            )
        except FileNotFoundError as exc:
            raise TTSError("không tìm thấy lệnh `say` — chỉ có trên macOS",
                           retryable=False) from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors="replace")[:400]
            raise TTSError(f"`say` thất bại với giọng `{voice}`: {detail}",
                           retryable=False) from exc

        duration = _finalize(raw, request.out_path, sample_rate=self.config.sample_rate)
        raw.unlink(missing_ok=True)

        return SynthesisResult(
            path=request.out_path, duration_ms=duration, voice=voice,
            provider=self.id, characters=len(request.text),
        )


class ElevenLabsProvider(TTSProvider):
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        cfg = self.config
        voice = request.voice or cfg.voice_for(request.locale)
        key = cfg.resolve_api_key()

        base = (cfg.base_url or "https://api.elevenlabs.io/v1").rstrip("/")
        try:
            response = httpx.post(
                f"{base}/text-to-speech/{voice}",
                headers={"xi-api-key": key or "", "Content-Type": "application/json"},
                json={
                    "text": request.text,
                    "model_id": cfg.model or "eleven_multilingual_v2",
                    **cfg.extra_body,
                },
                timeout=cfg.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise TTSError(f"lỗi kết nối: {exc}", retryable=True) from exc

        if response.status_code >= 400:
            raise TTSError(
                f"HTTP {response.status_code}: {response.text[:400]}",
                retryable=response.status_code in _RETRYABLE_STATUS,
            )

        raw = request.out_path.with_suffix(".mp3")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(response.content)

        duration = _finalize(raw, request.out_path, sample_rate=cfg.sample_rate)
        raw.unlink(missing_ok=True)

        return SynthesisResult(
            path=request.out_path, duration_ms=duration, voice=voice,
            provider=self.id, characters=len(request.text),
        )


class OpenAITTSProvider(TTSProvider):
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        cfg = self.config
        voice = request.voice or cfg.voice_for(request.locale)
        key = cfg.resolve_api_key()

        base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            response = httpx.post(
                f"{base}/audio/speech",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": cfg.model or "tts-1",
                    "voice": voice,
                    "input": request.text,
                    "speed": max(0.25, min(4.0, request.rate_scale)),
                    **cfg.extra_body,
                },
                timeout=cfg.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise TTSError(f"lỗi kết nối: {exc}", retryable=True) from exc

        if response.status_code >= 400:
            raise TTSError(
                f"HTTP {response.status_code}: {response.text[:400]}",
                retryable=response.status_code in _RETRYABLE_STATUS,
            )

        raw = request.out_path.with_suffix(".mp3")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(response.content)

        duration = _finalize(raw, request.out_path, sample_rate=cfg.sample_rate)
        raw.unlink(missing_ok=True)

        return SynthesisResult(
            path=request.out_path, duration_ms=duration, voice=voice,
            provider=self.id, characters=len(request.text),
        )


def apply_tempo(path: Path, ratio: float, out_path: Path | None = None) -> int:
    """Áp atempo lên file audio đã sinh — chiến lược fit #3 (§7.2).

    ffmpeg giới hạn atempo trong [0.5, 2.0] mỗi lần; ngưỡng an toàn của ta
    (0,92–1,08) nằm gọn bên trong nên không cần nối chuỗi filter.

    `ratio` là actual/target: >1 nghĩa là audio đang dài quá, phải đọc NHANH lên.
    """
    settings = get_settings()
    if not (settings.tempo_min <= ratio <= settings.tempo_max):
        raise ValueError(
            f"tempo {ratio} ngoài ngưỡng an toàn "
            f"[{settings.tempo_min}, {settings.tempo_max}] — tai người nghe ra ngay (§7.2)"
        )

    target = out_path or path
    tmp = target.with_name(f"{target.stem}__tempo{target.suffix}")
    run_ffmpeg(["-i", str(path), "-filter:a", f"atempo={ratio:.4f}",
                "-c:a", "pcm_s16le", str(tmp)])
    tmp.replace(target)
    return probe(target).duration_ms


TTS_ADAPTERS: dict[str, type[TTSProvider]] = {
    "macos_say": MacOSSayProvider,
    "elevenlabs": ElevenLabsProvider,
    "openai_tts": OpenAITTSProvider,
}
