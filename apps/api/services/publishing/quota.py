"""Quota manager — thuần, không I/O (§18.3).

> "một tool sinh 40 video/ngày mà chỉ đăng được 6 thì nút thắt nằm ở
> publishing" — nút thắt thật của batch là hạn mức nền tảng, không phải tốc
> độ render. Module này chỉ TÍNH, không tự đọc DB — `workers/publishing/stage.py`
> truyền vào số đơn vị đã dùng hôm nay (đếm từ `PublishingJob`).
"""

from __future__ import annotations

from dataclasses import dataclass

from services.publishing.base import PublishingConfig


@dataclass(frozen=True)
class QuotaStatus:
    used_units: int
    limit_units: int
    cost_per_upload_units: int

    @property
    def remaining_units(self) -> int:
        return max(0, self.limit_units - self.used_units)

    @property
    def remaining_uploads(self) -> int:
        return self.remaining_units // max(1, self.cost_per_upload_units)

    @property
    def can_publish_one_more(self) -> bool:
        return self.remaining_units >= self.cost_per_upload_units


def status_for(config: PublishingConfig, *, used_units_today: int) -> QuotaStatus:
    return QuotaStatus(
        used_units=used_units_today,
        limit_units=config.quota_daily_units,
        cost_per_upload_units=config.cost_per_upload_units,
    )
