"""Đọc lại độ dài intro/outro mà `compose` đã nối vào video (§6.14, §9).

`workers/compose/stage.py` nối intro/outro vào TRƯỚC `render` chạy, nhưng
audio (§9: TTS + background gốc) và phụ đề (SRT, §8.3) đều được dựng theo
timeline của NỘI DUNG CHÍNH — không biết gì về intro/outro. `render` phải tự
bù offset này khi mux (dịch audio + phụ đề tới đúng vị trí trong video đã có
intro), và `qc` phải tự cộng offset này vào ngưỡng thời lượng kỳ vọng — cả
hai đọc CHUNG hàm này để không lệch nhau về "đã cộng bao nhiêu".

Đọc TRỰC TIẾP từ `BrandProfile` qua `Project.brand_profile_id` — đúng field
mà `compose` dùng để quyết định có nối intro/outro hay không, không suy luận
riêng (§11.1: chia sẻ qua DB theo quy ước cố định, không qua output_ref).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.stage import StageContext
from db.models import BrandProfile, Project
from services.ffmpeg import probe


@dataclass(frozen=True)
class IntroOutroDurations:
    intro_ms: int
    outro_ms: int

    @property
    def total_ms(self) -> int:
        return self.intro_ms + self.outro_ms


def resolve_intro_outro_durations(ctx: StageContext) -> IntroOutroDurations:
    """(0, 0) nếu project chưa gán brand, brand không có intro/outro, hoặc
    file không còn trên đĩa — không raise: đây là bước ĐỌC LẠI một quyết định
    `compose` đã đưa ra, không phải bước tạo mới; thiếu dữ liệu ở đây có
    nghĩa hợp lý nhất là "không có gì được nối", không phải lỗi chặn."""
    project = ctx.session.get(Project, ctx.project_id)
    if project is None or not project.brand_profile_id:
        return IntroOutroDurations(0, 0)
    brand = ctx.session.get(BrandProfile, project.brand_profile_id)
    if brand is None:
        return IntroOutroDurations(0, 0)

    intro_ms = 0
    if brand.intro_path:
        p = ctx.storage.root / brand.intro_path
        if p.exists():
            intro_ms = probe(p).duration_ms

    outro_ms = 0
    if brand.outro_path:
        p = ctx.storage.root / brand.outro_path
        if p.exists():
            outro_ms = probe(p).duration_ms

    return IntroOutroDurations(intro_ms, outro_ms)
