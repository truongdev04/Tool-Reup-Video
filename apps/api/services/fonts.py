"""Font fallback cho hardsub (§13.2, §14).

Nối `font_stack` của locale preset (`services/presets.py`) vào filter
`subtitles` thật. Thiếu glyph là ra ô vuông — bug phát hiện muộn rất tốn thời
gian debug, đặc biệt với Ả Rập/Hindi/Thái mà ít ai test trước khi lên
production (§13.2). Nhúng sẵn font (`apps/api/assets/fonts/`, xem README ở đó)
thay vì trông cậy font hệ thống: libass/fontconfig VẪN tự tìm được fallback
qua font hệ thống khi thiếu (đã kiểm chứng thủ công: JA/AR render đúng trên
macOS nhờ Hiragino/Geeza Pro có sẵn), nhưng đó là hành vi KHÔNG ổn định giữa
các máy — một server không có các font hệ thống tương đương sẽ ra ô vuông.

Dùng ở hai chỗ: `workers/render/stage.py` (truyền `fontsdir`/`force_style`
vào filter thật) và `services/qc_media.py` (đo glyph coverage cho
`check_font_coverage`, xem qc.md) — cả hai đọc CHUNG một `FontResolution` để
không lệch giữa font đã RENDER và font QC đã KIỂM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FontResolution:
    #: Family truyền vào `force_style=FontName=...` — rỗng nếu `font_stack`
    #: rỗng hoặc không family nào trong stack có file đã bundle (khi đó filter
    #: KHÔNG áp force_style, để libass tự chọn như hành vi trước khi có
    #: tính năng này — không ép buộc một family không tồn tại).
    primary_family: str
    #: Thư mục chứa MỌI font đã bundle — libass tự quét theo tên family bên
    #: trong file, không cần chỉ định riêng file nào cho ký tự nào.
    fonts_dir: Path
    #: family -> đường dẫn file, chỉ gồm những family THẬT SỰ có file (dùng
    #: cho QC đo glyph coverage — không dùng để render).
    available: dict[str, Path] = field(default_factory=dict)


def _manifest(fonts_dir: Path) -> dict[str, str]:
    """`fonts_dir` là tham số (không đọc thẳng Settings) để test truyền được
    thư mục giả — module thuần theo dữ liệu đầu vào, không phụ thuộc ngầm."""
    path = fonts_dir / "manifest.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def resolve(font_stack: tuple[str, ...], fonts_dir: Path) -> FontResolution:
    """`font_stack` rỗng hoặc `fonts_dir` chưa có manifest -> coi như chưa cấu
    hình, không ép force_style (libass tự lo, đúng hành vi trước tính năng
    này) — thiếu font bundle không phải lý do chặn render."""
    manifest = _manifest(fonts_dir)
    available = {
        family: fonts_dir / filename
        for family, filename in manifest.items()
        if (fonts_dir / filename).exists()
    }
    primary = next((f for f in font_stack if f in available), "")
    return FontResolution(primary_family=primary, fonts_dir=fonts_dir, available=available)
