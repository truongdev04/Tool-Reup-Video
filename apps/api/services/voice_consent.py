"""Voice consent — chuyển ràng buộc pháp lý thành dữ liệu kiểm tra được (§18.2).

Bảng `voices` (model `Voice`) là nơi ĐĂNG KÝ một `provider_voice_id` cụ thể
LÀ giọng nhân bản (`is_cloned=True`) và consent nào cho phép dùng nó. TTS
hiện KHÔNG chọn giọng qua bảng này — nguồn thật là `config/tts/*.json` +
`Speaker.voice_mapping` (xem providers.md, diarization.md). `ensure_voice_consent`
chỉ TRA CỨU xem voice_id đang thực sự dùng có được đăng ký ở đây không:

- Chưa ai đăng ký (không có row khớp `provider`+`provider_voice_id`) -> coi
  như không phải giọng nhân bản, KHÔNG chặn. Đây không phải lỗ hổng — chỉ
  đăng ký được giọng người vận hành CHỦ ĐỘNG khai là bản sao của ai đó; không
  tự suy diễn `is_cloned` từ tên giọng.
- Có đăng ký, `is_cloned=True`, nhưng thiếu consent hoặc consent hết hạn/bị
  thu hồi -> chặn TTS bằng `NonRetryableError`, đúng yêu cầu §18.2 "TTS chặn
  nếu voice profile không có consent hợp lệ".

Giới hạn đã biết: chỉ enforce khi `TTSStage.run()` thực sự chạy. Một job đã
cache hit (§16) không đi qua lại đường này — consent bị thu hồi SAU khi audio
đã cache thì không tự động chặn việc tái dùng audio cũ đó.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.stage import NonRetryableError
from db.base import utcnow
from db.models import Voice


def ensure_voice_consent(session: Session, *, provider: str, voice_id: str | None) -> None:
    if not voice_id:
        return

    registered = session.scalars(
        select(Voice).where(Voice.provider == provider, Voice.provider_voice_id == voice_id)
    ).first()
    if registered is None or not registered.is_cloned:
        return

    consent = registered.consent
    if consent is None or not consent.is_valid_at(utcnow()):
        raise NonRetryableError(
            f"giọng `{voice_id}` (provider `{provider}`) được đăng ký là giọng nhân bản "
            f"(is_cloned=True) nhưng không có voice_consent còn hiệu lực — chặn TTS theo "
            f"§18.2. Thêm hoặc gia hạn bản ghi trong voice_consents rồi chạy lại."
        )
