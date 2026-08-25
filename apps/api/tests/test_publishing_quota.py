"""Quota manager thuần (§18.3) — services/publishing/quota.py."""

from __future__ import annotations

from services.publishing.base import PublishingConfig
from services.publishing.quota import status_for


def _config(**overrides) -> PublishingConfig:
    base = dict(
        id="x", name="x", adapter="mock",
        quota_daily_units=10_000, cost_per_upload_units=1_600,
    )
    base.update(overrides)
    return PublishingConfig(**base)


def test_con_du_quota_khi_chua_dung_gi():
    s = status_for(_config(), used_units_today=0)
    assert s.remaining_units == 10_000
    assert s.remaining_uploads == 6, "khớp số thật §18.3: 10000/1600 ≈ 6 video/ngày"
    assert s.can_publish_one_more


def test_gan_het_quota_khong_du_cho_1_video_nua():
    s = status_for(_config(), used_units_today=9_600)
    assert s.remaining_units == 400
    assert s.remaining_uploads == 0
    assert not s.can_publish_one_more, "400 đơn vị còn lại < 1600 chi phí mỗi lần đăng"


def test_dung_vuot_gioi_han_khong_bi_am():
    s = status_for(_config(), used_units_today=99_999)
    assert s.remaining_units == 0
    assert not s.can_publish_one_more
