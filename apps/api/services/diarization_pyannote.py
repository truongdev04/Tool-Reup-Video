"""Backend diarization thật — pyannote.audio (docs §6.5).

Ba điều kiện phải có trước khi dùng được:

1. **Cài đặt**: `.venv/bin/pip install pyannote.audio` — không nằm trong
   `pyproject.toml` mặc định vì kéo theo torch/lightning/speechbrain (nặng),
   chỉ cài khi thật sự bật diarization (theo đúng comment trong pyproject:
   "thêm dần khi implement từng module, không cài trước những gì chưa cần").
2. **Chấp nhận điều khoản trên HuggingFace** cho CẢ HAI model — pipeline
   diarization tải `segmentation-3.0` ngầm bên trong, thiếu accept model con
   này thì tải model cha vẫn báo lỗi quyền truy cập:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. **Access token**: tạo tại https://huggingface.co/settings/tokens (quyền
   đọc là đủ), đặt vào biến môi trường `HF_TOKEN`.

`HF_TOKEN` là tên biến CHUẨN của hệ sinh thái HuggingFace (huggingface_hub,
transformers, pyannote đều đọc thẳng biến này) — không đi qua cơ chế
`api_key_env` khai trong JSON như `services/providers/`, `services/tts/`, vì
đó là quy ước cho provider PLUG-IN (nhiều lựa chọn); ở đây chỉ có một backend
diarization nên không cần lớp gián tiếp đó. Đọc token tại thời điểm gọi, không
lưu DB/log, đúng quy ước chung (providers.md).
"""

from __future__ import annotations

import os
from pathlib import Path

from workers.diarization.assign import DiarizationTurn

#: Tên biến môi trường chuẩn của HuggingFace Hub, xem docstring module.
HF_TOKEN_ENV = "HF_TOKEN"


class DiarizationUnavailable(RuntimeError):
    """Lý do không chạy được diarization thật ngay bây giờ.

    KHÔNG phải lỗi chương trình — `workers/diarization/stage.py` bắt exception
    này để quyết định BỎ QUA diarization thay vì chặn cả pipeline (xem
    docstring của stage đó về lý do không dùng NonRetryableError ở đây).
    """


def check_available() -> None:
    """Không làm gì nếu sẵn sàng chạy thật; raise `DiarizationUnavailable` kèm
    lý do cụ thể (thiếu thư viện hay thiếu token) nếu chưa."""
    try:
        import pyannote.audio  # noqa: F401
    except ImportError as exc:
        raise DiarizationUnavailable(
            "chưa cài `pyannote.audio` (.venv/bin/pip install pyannote.audio)"
        ) from exc
    if not os.environ.get(HF_TOKEN_ENV):
        raise DiarizationUnavailable(
            f"thiếu biến môi trường `{HF_TOKEN_ENV}` — cần access token đã chấp "
            "nhận điều khoản pyannote/speaker-diarization-3.1 trên HuggingFace "
            "(xem hướng dẫn trong docstring module này)"
        )


def run_diarization(
    audio_path: Path,
    *,
    model: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[DiarizationTurn]:
    """Chạy pipeline pyannote thật trên `audio_path`, trả các lượt nói theo
    thứ tự thời gian.

    Gọi `check_available()` trước khi gọi hàm này — hàm này không tự kiểm tra
    lại để tránh hai đường sinh ra hai thông báo lỗi khác nhau cho cùng một
    nguyên nhân.
    """
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(model, use_auth_token=os.environ[HF_TOKEN_ENV])
    kwargs: dict[str, int] = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers
    annotation = pipeline(str(audio_path), **kwargs)

    turns = [
        DiarizationTurn(
            start_ms=round(turn.start * 1000),
            end_ms=round(turn.end * 1000),
            speaker=str(speaker),
        )
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda t: t.start_ms)
    return turns
