"""Adapter cho từng nền tảng publishing — docs §6.17, §18.1.

Chỉ có `mock` ở lượt này (§20 Phase 5 "scaffold đầy đủ") — đủ để test toàn
bộ luồng OAuth (authorize/callback/refresh) + quota + publish THẬT qua trình
duyệt, không cần app OAuth thật của YouTube/TikTok/Instagram. Thêm nền tảng
thật: thêm 1 class ở đây implement `PublishingProvider`, đăng ký vào
`ADAPTERS`, và 1 file JSON trong `config/publishing/` — xem
`.claude/rules/publishing.md`.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from services.publishing.base import (
    PublishingConfig,
    PublishingError,
    PublishingProvider,
    PublishRequest,
    PublishResult,
    TokenSet,
)

#: Đặt vào title để test đường lỗi publish mà không cần nền tảng thật trả lỗi.
FAIL_MARKER = "FAIL_MOCK_PUBLISH"


class MockPublishingProvider(PublishingProvider):
    """Nền tảng giả — 'authorization server' và 'upload API' đều do chính
    backend của ta đóng vai (`api/routes/publishing.py::mock_consent`),
    KHÔNG gọi ra ngoài. Token là chuỗi giả nhưng đi qua ĐÚNG luồng mã hoá/lưu
    DB như token thật (§18.1)."""

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        # Đường dẫn TƯƠNG ĐỐI — route gọi hàm này (api/routes/publishing.py)
        # tự resolve thành URL tuyệt đối theo host đang chạy (không hard-code
        # port, vì cổng dev có thể đổi — xem .claude/rules/infra.md mục cổng).
        qs = urlencode({"state": state, "redirect_uri": redirect_uri, "platform": self.config.id})
        return f"/api/dashboard/publishing/mock/consent?{qs}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> TokenSet:
        if not code.startswith("mock-"):
            raise PublishingError(f"code không hợp lệ cho mock provider: `{code}`", retryable=False)
        return TokenSet(
            access_token=f"mock-access-{uuid.uuid4().hex[:12]}",
            refresh_token=f"mock-refresh-{uuid.uuid4().hex[:12]}",
            expires_in_s=3600,
        )

    def refresh(self, *, refresh_token: str) -> TokenSet:
        if not refresh_token.startswith("mock-refresh-"):
            raise PublishingError("refresh_token không hợp lệ cho mock provider", retryable=False)
        return TokenSet(
            access_token=f"mock-access-{uuid.uuid4().hex[:12]}",
            refresh_token=refresh_token,
            expires_in_s=3600,
        )

    def publish(self, request: PublishRequest) -> PublishResult:
        if not request.access_token.startswith("mock-access-"):
            raise PublishingError("access_token không hợp lệ cho mock provider", retryable=False)
        if not request.video_path.exists() or request.video_path.stat().st_size == 0:
            raise PublishingError(f"video không tồn tại/rỗng: {request.video_path}", retryable=False)
        if FAIL_MARKER in request.title:
            raise PublishingError(
                f"mock provider giả lập lỗi publish (title chứa `{FAIL_MARKER}`)", retryable=True,
            )
        return PublishResult(
            platform_video_id=f"mock-video-{uuid.uuid4().hex[:12]}",
            raw={
                "title": request.title, "hashtags": request.hashtags,
                "ai_disclosure": request.ai_disclosure,
            },
        )


ADAPTERS: dict[str, type[PublishingProvider]] = {
    "mock": MockPublishingProvider,
}


def build(config: PublishingConfig) -> PublishingProvider:
    adapter = ADAPTERS.get(config.adapter)
    if adapter is None:
        raise PublishingError(
            f"provider publishing `{config.id}` khai adapter `{config.adapter}` không tồn tại. "
            f"Đang hỗ trợ: {', '.join(sorted(ADAPTERS))}",
            retryable=False,
        )
    return adapter(config)
