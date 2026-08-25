"""Cấu hình runtime. Không hard-code provider/đường dẫn trong source (docs §2.2)."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _find_ffmpeg(binary: str) -> str:
    """Ưu tiên ffmpeg-full của Homebrew.

    Bản `ffmpeg` thường của Homebrew KHÔNG có libass/freetype nên thiếu filter
    `subtitles`, `ass` và `drawtext` — không burn được hardsub và không vẽ được
    text branding (docs §6.11, §6.14, §13.2). `ffmpeg-full` là keg-only nên
    không nằm trong PATH, phải trỏ đường dẫn tuyệt đối.
    """
    keg_only = Path(f"/opt/homebrew/opt/ffmpeg-full/bin/{binary}")
    if keg_only.exists():
        return str(keg_only)
    return shutil.which(binary) or binary


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VLA_",
        env_file=(_REPO_ROOT / "apps/api/.env", _REPO_ROOT / ".env"),
        extra="ignore",
    )

    ffmpeg_bin: str = Field(default_factory=lambda: _find_ffmpeg("ffmpeg"))
    ffprobe_bin: str = Field(default_factory=lambda: _find_ffmpeg("ffprobe"))

    database_url: str = f"sqlite:///{_REPO_ROOT / 'vla.db'}"
    storage_root: Path = _REPO_ROOT / "storage"
    #: Font Noto nhúng sẵn cho hardsub — không trông cậy font hệ thống, hành vi
    #: phải giống nhau trên mọi máy chạy pipeline (docs §13.2, §14). Xem
    #: `apps/api/assets/fonts/README.md`, `services/fonts.py`.
    fonts_dir: Path = _REPO_ROOT / "apps/api/assets/fonts"

    #: Bump khi đổi logic pipeline theo cách làm output cũ không còn hợp lệ.
    #: Nằm trong cache key nên bump = vô hiệu hoá toàn bộ cache (docs §16).
    config_version: str = "0.1.0"

    #: Ngưỡng QC quan trọng nhất của hệ thống (docs §15, §21).
    max_cumulative_drift_ms: int = 300
    #: Ngưỡng an toàn khi chỉnh tempo TTS (docs §7.2) — vượt là tai nghe ra ngay.
    tempo_min: float = 0.92
    tempo_max: float = 1.08
    #: Khoảng lặng tối thiểu phải chừa lại khi "ăn" vào silence (docs §7.2).
    min_silence_keep_ms: int = 150

    #: Model diarization trên HuggingFace Hub (docs §6.5). Đây là model GATED —
    #: phải bấm "Agree" trên trang model (và trang `pyannote/segmentation-3.0`
    #: nó phụ thuộc) rồi mới xin access token dùng được, xem
    #: `services/diarization_pyannote.py`.
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    #: None = để pyannote tự đoán số người nói.
    diarization_min_speakers: int | None = None
    diarization_max_speakers: int | None = None

    #: Broker/backend Celery (§20, Phase 3) — Redis LOCAL trên máy chạy
    #: worker (`brew install redis`), không phải server từ xa. Xem
    #: core/celery_app.py, .claude/rules/infra.md.
    redis_url: str = "redis://localhost:6379/0"

    #: Khoá mã hoá OAuth token trước khi lưu DB (§18.1, Phase 5) — base64
    #: Fernet key (`Fernet.generate_key()`). None ở dev/test thì
    #: `services/crypto.py` tự sinh khoá TẠM (mất khi restart) kèm cảnh báo —
    #: KHÔNG dùng mặc định đó ở môi trường có token thật. Xem
    #: .claude/rules/publishing.md.
    token_encryption_key: str | None = None

    @field_validator("storage_root")
    @classmethod
    def _resolve(cls, v: Path) -> Path:
        return v.expanduser().resolve()

    def verify_ffmpeg(self) -> list[str]:
        """Trả về danh sách khả năng còn thiếu. Rỗng = đủ dùng cho pipeline."""
        import subprocess

        missing: list[str] = []
        try:
            filters = subprocess.run(
                [self.ffmpeg_bin, "-hide_banner", "-filters"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            return [f"không chạy được {self.ffmpeg_bin}: {exc}"]

        required = {
            "subtitles": "burn hardsub (§6.11)",
            "ass": "render ASS (§6.11)",
            "drawtext": "vẽ text branding/CTA (§6.14)",
            "loudnorm": "chuẩn hoá loudness EBU R128 (§9)",
            "sidechaincompress": "ducking BGM (§9)",
            "atempo": "chỉnh tempo khi duration fit (§7.2)",
        }
        for name, why in required.items():
            if f" {name} " not in filters:
                missing.append(f"thiếu filter `{name}` — cần cho {why}")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
