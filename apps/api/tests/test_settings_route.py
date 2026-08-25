"""Test cho `api/routes/settings.py` — trang Settings dashboard READ-ONLY.

Gọi thẳng hàm route (không qua `TestClient`/HTTP) vì `get_settings_status()`
không nhận `Request`/session nào — cùng kiểu test hàm thuần đã dùng cho
`services/publishing/quota.py` (§18.3).
"""

from __future__ import annotations

from api.routes.settings import get_settings_status
from core.types import ArtifactKind
from services.storage import RETENTION_DAYS


def test_settings_co_du_cac_muc_chinh():
    """Trang Settings phải liệt kê đủ mọi nhóm — thiếu một nhóm là dashboard
    thiếu thông tin vận hành mà không có cảnh báo nào."""
    data = get_settings_status()
    for key in (
        "config_version", "ffmpeg", "translation_providers", "tts_providers",
        "publishing_platforms", "retention_days", "thresholds", "diarization",
        "infra",
    ):
        assert key in data, f"thiếu mục `{key}` trong response Settings"


def test_retention_days_khop_voi_moi_artifact_kind():
    """Response phải phản ánh ĐÚNG `RETENTION_DAYS` thật (không hard-code lại
    trong route) — lệch nhau nghĩa là Settings nói dối vận hành viên."""
    data = get_settings_status()
    assert set(data["retention_days"]) == {k.value for k in ArtifactKind}
    for kind, days in RETENTION_DAYS.items():
        assert data["retention_days"][kind.value] == days


def test_khong_lo_api_key_that_ra_response(monkeypatch):
    """Đây là ràng buộc bảo mật quan trọng nhất của trang này (§18.1): dù
    provider đã cấu hình key thật, response CHỈ được nói `is_configured=True`,
    không bao giờ trả lại giá trị key."""
    fake_key = "sk-test-khong-duoc-lo-ra-ngoai"
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)

    data = get_settings_status()

    openai_entry = next(p for p in data["translation_providers"] if p["id"] == "openai")
    assert openai_entry["is_configured"] is True
    assert openai_entry["api_key_env"] == "OPENAI_API_KEY"

    import json
    serialized = json.dumps(data)
    assert fake_key not in serialized, "API key thật bị lộ ra response Settings"


def test_provider_thieu_key_bao_chua_cau_hinh():
    """Provider cần key nhưng biến môi trường trống phải hiện đúng trạng thái
    `is_configured=False` — vận hành viên dựa vào cờ này để biết provider nào
    dùng được ngay."""
    data = get_settings_status()
    openrouter = next(
        (p for p in data["translation_providers"] if p["id"] == "openrouter"), None
    )
    assert openrouter is not None
    if not openrouter["is_configured"]:
        assert openrouter["needs_api_key"] is True


def test_diarization_khong_lo_hf_token_that(monkeypatch):
    """`HF_TOKEN` là biến chuẩn của huggingface_hub (khác `api_key_env` kiểu
    JSON của các provider khác — xem diarization.md) — vẫn phải qua cùng
    nguyên tắc không lộ giá trị thật."""
    fake_token = "hf_test-token-khong-duoc-lo"
    monkeypatch.setenv("HF_TOKEN", fake_token)

    data = get_settings_status()

    assert data["diarization"]["hf_token_configured"] is True
    import json
    assert fake_token not in json.dumps(data)


def test_ffmpeg_status_dung_ket_qua_verify_ffmpeg_that():
    """`ok=True` khi và chỉ khi `verify_ffmpeg()` không báo thiếu filter nào —
    Settings không được tự suy luận riêng, phải dùng đúng hàm kiểm tra thật
    mà `Settings.verify_ffmpeg()` đã định nghĩa (environment.md)."""
    from core.config import get_settings

    data = get_settings_status()
    missing = get_settings().verify_ffmpeg()
    assert data["ffmpeg"]["ok"] == (not missing)
    assert data["ffmpeg"]["missing"] == missing
