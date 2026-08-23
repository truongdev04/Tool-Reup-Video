"""Nạp preset từ file — docs §14.

Preset KHÔNG hard-code trong source (§2.2). Mỗi loại preset là một thư mục
trong `config/presets/`, mỗi preset là một file JSON đặt tên theo id của nó.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PRESET_ROOT = Path(__file__).resolve().parents[1] / "config" / "presets"


class PresetNotFound(KeyError):
    pass


@dataclass(frozen=True)
class LocalePreset:
    """Đặc tính ngôn ngữ đích — chi phối Segment Planner (§5), Duration Fitting
    (§7) và Subtitle (§8).
    """

    locale: str
    name: str
    script: str
    direction: str
    line_break: str
    chars_per_line: int
    max_lines: int
    cps_max: float
    #: Số ký tự đọc được trong 1 giây — dùng để tính char_budget khi dịch (§7.2).
    #:
    #: CẢNH BÁO: các giá trị mặc định là ước lượng ban đầu, CHƯA hiệu chuẩn với
    #: TTS thật. Sai số ở đây đẩy thẳng vào drift. Phải đo lại bằng
    #: `scripts/calibrate_speech_rate.py` sau khi chốt provider TTS (§23 #3),
    #: rồi ghi đè vào file preset.
    speech_rate_cps: float
    min_cue_ms: int
    max_cue_ms: int
    sentence_enders: tuple[str, ...]
    font_stack: tuple[str, ...] = ()
    #: True khi số liệu speech_rate_cps đã được đo từ TTS thật, không còn là ước lượng.
    speech_rate_calibrated: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_cjk(self) -> bool:
        return self.line_break == "cjk"

    @property
    def is_rtl(self) -> bool:
        return self.direction == "rtl"

    def char_budget_for(self, duration_ms: int) -> int:
        """Số ký tự bản dịch nên có để đọc vừa `duration_ms` (§7.2 chiến lược 1)."""
        return max(1, round(duration_ms / 1000 * self.speech_rate_cps))

    def duration_for(self, char_count: int) -> int:
        """Ước thời lượng đọc của một đoạn text, tính bằng ms."""
        return max(0, round(char_count / self.speech_rate_cps * 1000))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def load_locale(locale: str) -> LocalePreset:
    path = PRESET_ROOT / "locale" / f"{locale}.json"
    if not path.exists():
        available = sorted(p.stem for p in (PRESET_ROOT / "locale").glob("*.json"))
        raise PresetNotFound(
            f"chưa có locale preset `{locale}`. Đang có: {', '.join(available) or 'không có'}. "
            f"Thêm file {path}"
        )
    data = _load_json(path)
    return LocalePreset(
        locale=data["locale"],
        name=data["name"],
        script=data["script"],
        direction=data["direction"],
        line_break=data["line_break"],
        chars_per_line=int(data["chars_per_line"]),
        max_lines=int(data["max_lines"]),
        cps_max=float(data["cps_max"]),
        speech_rate_cps=float(data["speech_rate_cps"]),
        min_cue_ms=int(data["min_cue_ms"]),
        max_cue_ms=int(data["max_cue_ms"]),
        sentence_enders=tuple(data.get("sentence_enders", (".", "!", "?"))),
        font_stack=tuple(data.get("font_stack", ())),
        speech_rate_calibrated=bool(data.get("speech_rate_calibrated", False)),
        raw=data,
    )


def available_locales() -> list[str]:
    return sorted(p.stem for p in (PRESET_ROOT / "locale").glob("*.json"))
