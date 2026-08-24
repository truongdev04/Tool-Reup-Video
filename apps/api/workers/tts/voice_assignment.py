"""Chọn voice TTS theo speaker — nối `diarize` (§6.5) vào `tts` (§6.9).

Nhiều speaker cùng đọc một giọng nghe lẫn lộn, nhất là hội thoại nhiều người.
`diarize` (`workers/diarization/`) gán `speaker_id` cho từng `translation_unit`
khi chạy được (cần `pyannote.audio` + `HF_TOKEN`, xem `.claude/rules/diarization.md`)
— module này map speaker đó sang voice id thật của provider TTS đang dùng.

Module thuần: nhận `SpeakerInfo` đã đọc sẵn từ DB + cấu hình provider, KHÔNG
tự truy vấn/ghi DB — theo đúng mẫu tách thuần/I-O của dự án (coding-style.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerInfo:
    id: str
    label: str
    #: `Speaker.voice_mapping.get(locale)` nếu đã có người set thủ công —
    #: LUÔN thắng thứ tự tự động gán bên dưới.
    manual_voice: str | None = None


def resolve_voice_assignment(
    speakers: list[SpeakerInfo], *, default_voice: str, alt_voices: list[str],
) -> dict[str, str]:
    """speaker_id -> voice, cho MỌI speaker trong `speakers`.

    Speaker ĐẦU TIÊN (theo `label` sắp xếp, ổn định giữa các lần chạy) luôn
    nhận `default_voice` — giữ nguyên hành vi khi chỉ có một người nói: không
    đổi so với trước khi có diarize, không phá cache của video đơn thoại đã
    chạy trước đó (`voices[locale]` của provider vẫn là giọng ai cũng nghe
    quen). Speaker thứ 2 trở đi lấy lần lượt từ `alt_voices`; hết pool thì
    quay lại `default_voice` (mọi người nghe giống nhau) thay vì lỗi — thiếu
    voice phụ cấu hình cho provider/locale này không phải lý do chặn pipeline
    (cùng tinh thần "bỏ qua, không chặn" của `diarize`, xem diarization.md).

    Speaker có `manual_voice` (người dùng đã set `Speaker.voice_mapping`) LUÔN
    được ưu tiên, không bị thứ tự tự động ở trên ghi đè.
    """
    ordered = sorted(speakers, key=lambda s: s.label)
    result: dict[str, str] = {}
    alt_idx = 0
    for i, sp in enumerate(ordered):
        if sp.manual_voice:
            result[sp.id] = sp.manual_voice
        elif i == 0:
            result[sp.id] = default_voice
        elif alt_idx < len(alt_voices):
            result[sp.id] = alt_voices[alt_idx]
            alt_idx += 1
        else:
            result[sp.id] = default_voice
    return result
