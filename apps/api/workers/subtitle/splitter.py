"""Cắt text thành subtitle cue theo giới hạn đọc — docs §6.11, §8.

Module thuần: nhận text + timestamp cấp ký tự (từ forced_align), trả về danh
sách cue tuân thủ chars_per_line/max_lines/cps_max/min_cue_ms của locale.
Hoạt động trên MỘT translation_unit — cue không nối liền qua ranh giới hai
unit khác nhau (mỗi unit là một câu/ý và có thể khác speaker, gộp cue qua ranh
giới đó dễ tạo cue lẫn lộn ngữ cảnh).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from services.presets import LocalePreset
from workers.forced_align.aligner import span_duration_ms

_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class Atom:
    """Đơn vị nguyên tử không thể chia nhỏ thêm: một từ (Latin/RTL) hoặc một
    ký tự (CJK)."""

    start_char: int
    end_char: int
    text: str

    @property
    def length(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    lines: list[str]
    cps: float


def _tokenize(text: str, preset: LocalePreset) -> list[Atom]:
    if preset.is_cjk:
        return [
            Atom(i, i + 1, ch) for i, ch in enumerate(text) if not ch.isspace()
        ]
    return [Atom(m.start(), m.end(), m.group()) for m in _WORD_RE.finditer(text)]


def _join(atoms: list[Atom], preset: LocalePreset) -> str:
    sep = "" if preset.is_cjk else " "
    return sep.join(a.text for a in atoms)


def split_unit_into_cues(
    text: str,
    char_boundaries_ms: list[int],
    unit_start_ms: int,
    preset: LocalePreset,
    *,
    display_end_limit_ms: int | None = None,
) -> list[Cue]:
    """Cắt text của một translation_unit thành cue, timestamp TUYỆT ĐỐI.

    `char_boundaries_ms` là mốc TƯƠNG ĐỐI so với đầu audio của unit (từ
    `forced_align`); `unit_start_ms` dịch chúng sang trục thời gian tuyệt đối
    của video.

    `display_end_limit_ms` là mốc TUYỆT ĐỐI xa nhất mà CUE CUỐI của unit này
    được phép kéo dài tới khi chưa đủ `min_cue_ms` (§6.11) — người xem cần
    nhiều thời gian ĐỌC hơn thời gian NGHE, đặc biệt với câu rất ngắn. Caller
    (stage subtitle) nên truyền vào điểm bắt đầu của unit kế tiếp, vì bản thân
    hàm này chỉ biết audio của MỘT unit nên không tự suy ra được còn bao nhiêu
    chỗ trống trước khi lời thoại tiếp theo bắt đầu. Bỏ trống thì mặc định
    không kéo dài quá điểm kết thúc audio của chính unit này.
    """
    atoms = _tokenize(text, preset)
    if not atoms:
        return []

    cues: list[Cue] = []
    lines: list[list[Atom]] = [[]]

    def flat() -> list[Atom]:
        return [a for line in lines for a in line]

    def span_ms() -> int:
        current = flat()
        if not current:
            return 0
        return span_duration_ms(char_boundaries_ms, current[0].start_char, current[-1].end_char)

    def chars() -> int:
        return sum(a.length for a in flat())

    def cps() -> float:
        s = span_ms()
        return chars() / (s / 1000) if s > 0 else 0.0

    def close_cue() -> None:
        nonlocal lines
        text_lines = [_join(line, preset) for line in lines if line]
        if text_lines:
            current = flat()
            start = char_boundaries_ms[current[0].start_char] + unit_start_ms
            end = char_boundaries_ms[current[-1].end_char] + unit_start_ms
            cues.append(Cue(start_ms=start, end_ms=end, lines=text_lines, cps=round(cps(), 2)))
        lines = [[]]

    for atom in atoms:
        # Trạng thái TRƯỚC khi thêm atom — quyết định có được phép tách vì lý
        # do CPS hay không dựa vào việc cue đã đủ dài để đứng một mình chưa.
        prior = flat()
        prior_span_ms = (
            span_duration_ms(char_boundaries_ms, prior[0].start_char, prior[-1].end_char)
            if prior else 0
        )

        trial_line = lines[-1] + [atom]
        if len(_join(trial_line, preset)) <= preset.chars_per_line or not lines[-1]:
            # Vừa dòng hiện tại, hoặc dòng đang rỗng nên buộc phải nhận (atom
            # dài hơn cả giới hạn dòng — không có cách nào chia nhỏ thêm).
            lines[-1] = trial_line
        elif len(lines) < preset.max_lines:
            lines.append([atom])
        else:
            close_cue()
            lines = [[atom]]

        overflow = cps() > preset.cps_max or span_ms() > preset.max_cue_ms
        #: Chỉ tách vì CPS/max_cue_ms khi cue TRƯỚC atom này đã đủ dài để đứng
        #: một mình (>= min_cue_ms). Không có điều kiện này, giọng đọc nhanh
        #: hơn cps_max một chút (rất hay gặp — TTS thường nhanh hơn ngưỡng đọc
        #: thoải mái) sẽ khiến MỌI cặp từ liên tiếp đều "vượt ngưỡng", tách
        #: thành cue 1 từ nhấp nháy suốt video — trải nghiệm tệ hơn nhiều so
        #: với một cue hơi nhanh nhưng đọc được trọn vẹn.
        already_legible = prior_span_ms >= preset.min_cue_ms
        if overflow and chars() > atom.length and already_legible:
            # Cue hiện tại (không tính atom vừa thêm) đã đủ nội dung — tách
            # atom này sang cue mới thay vì để cue đọc quá nhanh/quá dài.
            last_line = lines[-1]
            last_line.pop()
            if not last_line and len(lines) > 1:
                lines.pop()
            close_cue()
            lines = [[atom]]

    close_cue()
    natural_end_ms = char_boundaries_ms[-1] + unit_start_ms
    hard_end_ms = display_end_limit_ms if display_end_limit_ms is not None else natural_end_ms
    return _enforce_min_duration(cues, preset.min_cue_ms, hard_end_ms=hard_end_ms)


def _enforce_min_duration(cues: list[Cue], min_ms: int, *, hard_end_ms: int) -> list[Cue]:
    """Cue quá ngắn thì kéo dài đến khi đủ `min_ms`, không vượt quá cue kế tiếp
    (hoặc điểm kết audio của unit nếu là cue cuối)."""
    out: list[Cue] = []
    for i, cue in enumerate(cues):
        if cue.end_ms - cue.start_ms >= min_ms:
            out.append(cue)
            continue
        limit = cues[i + 1].start_ms if i + 1 < len(cues) else hard_end_ms
        new_end = min(cue.start_ms + min_ms, max(limit, cue.end_ms))
        duration_s = max(0.001, (new_end - cue.start_ms) / 1000)
        chars = sum(len(line) for line in cue.lines)
        out.append(replace(cue, end_ms=new_end, cps=round(chars / duration_s, 2)))
    return out
