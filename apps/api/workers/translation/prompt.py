"""Dựng prompt dịch — docs §6.7.

Prompt phải tải được bốn ràng buộc cùng lúc:
  1. Budget ký tự cho từng đơn vị — chiến lược ép thời lượng rẻ nhất (§7.2 #1)
  2. Glossary — tên sản phẩm và thuật ngữ giữ nguyên
  3. Ngữ cảnh trước/sau — dịch từng câu rời rạc là mất mạch (§5)
  4. Transcreation cho hook/CTA — dịch sát làm hỏng hai chỗ này (§6.7)
"""

from __future__ import annotations

import json

from services.providers.base import TranslationRequest

_SYSTEM = """\
Bạn là chuyên gia bản địa hoá video. Nhiệm vụ: dịch lời thoại từ {source} sang \
{target} để lồng tiếng.

Ràng buộc bắt buộc:

1. ĐỘ DÀI. Mỗi đơn vị có `char_budget` — số ký tự tối đa để đọc vừa khung hình. \
Bám sát budget: diễn đạt lại, rút gọn, chọn từ ngắn hơn. Vượt budget làm audio \
trôi khỏi hình. Đây là ràng buộc quan trọng nhất.

2. GIỮ NGUYÊN. Tên riêng, tên sản phẩm, tên thương hiệu và thuật ngữ trong \
glossary giữ đúng như đã cho.

3. VĂN NÓI. Đây là lời nói, không phải văn viết. Dịch sao cho đọc lên nghe tự \
nhiên trong {target}.

4. BẢN ĐỊA HOÁ SỐ LIỆU. Ngày tháng, đơn vị đo, tiền tệ và định dạng số chuyển \
theo quy ước của {target}.

5. TRANSCREATION. Đơn vị có `transcreate: true` là hook mở đầu hoặc lời kêu gọi \
hành động — dịch thoáng để giữ sức thuyết phục, không dịch sát từng chữ.

Chỉ trả về JSON, không thêm lời dẫn, không bọc trong markdown:
[{{"idx": <số>, "text": "<bản dịch>"}}]

Phải trả đủ MỌI idx được yêu cầu."""


def build_messages(request: TranslationRequest) -> tuple[str, str]:
    """Trả về (system_prompt, user_prompt)."""
    system = _SYSTEM.format(source=request.source_locale, target=request.target_locale)

    parts: list[str] = []

    if request.glossary:
        entries = "\n".join(f"  {k} → {v}" for k, v in request.glossary.items())
        parts.append(f"GLOSSARY (bắt buộc dùng đúng):\n{entries}")

    if request.style_guide:
        parts.append(f"STYLE GUIDE:\n{request.style_guide}")

    # Ngữ cảnh chỉ để hiểu mạch, tuyệt đối không dịch — nếu không model sẽ trả
    # thừa đơn vị và phá vỡ mapping idx.
    if request.context_before:
        parts.append(f"NGỮ CẢNH phía trước (KHÔNG dịch):\n  {request.context_before}")
    if request.context_after:
        parts.append(f"NGỮ CẢNH phía sau (KHÔNG dịch):\n  {request.context_after}")

    payload = [
        {
            "idx": item.idx,
            "text": item.text,
            "char_budget": item.char_budget,
            "transcreate": item.needs_transcreation,
            **({"speaker": item.speaker} if item.speaker else {}),
        }
        for item in request.items
    ]
    parts.append(
        "CẦN DỊCH — trả đủ "
        f"{len(payload)} đơn vị:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )

    return system, "\n\n".join(parts)


def over_budget(text: str, char_budget: int | None, *, slack: float = 0.15) -> bool:
    """Bản dịch có vượt budget quá mức cho phép không.

    Cho phép dôi ra một chút vì Duration Fitting còn ba bậc nữa để xử lý phần dư
    (§7.2); vượt nhiều hơn mới đáng gọi lại model.
    """
    if not char_budget:
        return False
    return len(text) > char_budget * (1 + slack)
