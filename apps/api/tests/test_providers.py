"""Provider abstraction — docs §2.2, §6.7, §16.

Không test nào ở đây gọi mạng.
"""

from __future__ import annotations

import json

import pytest

from services.providers.adapters import ADAPTERS, _parse_translations
from services.providers.base import (
    MissingAPIKey,
    ProviderConfig,
    ProviderError,
    TranslationItem,
    TranslationRequest,
)
from services.providers.registry import (
    ProviderNotFound,
    available,
    get_provider,
    load_config,
)
from workers.translation.prompt import build_messages, over_budget


@pytest.fixture
def request_2_units():
    return TranslationRequest(
        items=[
            TranslationItem(idx=0, text="Stop scrolling.", char_budget=20,
                            needs_transcreation=True),
            TranslationItem(idx=1, text="This is the middle part.", char_budget=40),
        ],
        source_locale="en-US",
        target_locale="es-ES",
        glossary={"Tool Reup": "Tool Reup"},
        style_guide="Giọng thân mật.",
        context_before="Câu trước đó.",
    )


# --- registry ---------------------------------------------------------------

def test_moi_provider_khai_bao_deu_nap_duoc():
    assert available(), "phải có ít nhất một provider"
    for pid in available():
        config = load_config(pid)
        assert config.adapter in ADAPTERS, f"{pid} khai adapter lạ: {config.adapter}"
        assert config.model, f"{pid} thiếu model"


def test_them_provider_moi_chi_can_file_json(tmp_path, monkeypatch):
    """Yêu cầu cốt lõi: thêm provider không phải sửa code (§2.2)."""
    from services.providers import registry

    monkeypatch.setattr(registry, "PROVIDER_ROOT", tmp_path)
    (tmp_path / "custom.json").write_text(json.dumps({
        "id": "custom",
        "name": "Nhà cung cấp tự thêm",
        "adapter": "openai_compatible",
        "base_url": "https://example.invalid/v1",
        "model": "some-model",
        "api_key_env": "CUSTOM_KEY",
    }), encoding="utf-8")

    provider = registry.get_provider("custom")
    assert provider.id == "custom"
    assert provider.config.base_url == "https://example.invalid/v1"


def test_provider_khong_ton_tai_bao_loi_ro_rang():
    with pytest.raises(ProviderNotFound, match="Đang có"):
        get_provider("khong-co-dau")


def test_config_co_truong_la_thi_bao_loi(tmp_path, monkeypatch):
    """Gõ sai tên trường mà im lặng bỏ qua thì cấu hình không có tác dụng."""
    from services.providers import registry

    monkeypatch.setattr(registry, "PROVIDER_ROOT", tmp_path)
    (tmp_path / "typo.json").write_text(json.dumps({
        "id": "typo", "name": "x", "adapter": "mock", "model": "m",
        "temperatur": 0.5,
    }), encoding="utf-8")

    with pytest.raises(ProviderError, match="trường lạ"):
        registry.load_config("typo")


# --- API key ----------------------------------------------------------------

def test_thieu_api_key_bao_loi_khong_retry(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = load_config("openai")
    with pytest.raises(MissingAPIKey) as exc:
        config.resolve_api_key()
    assert not exc.value.retryable, "thiếu key thì retry bao nhiêu lần cũng vậy"
    assert "OPENAI_API_KEY" in str(exc.value)


def test_provider_local_khong_can_key():
    for pid in ("ollama", "lmstudio", "mock"):
        config = load_config(pid)
        assert not config.needs_api_key
        assert config.resolve_api_key() is None
        assert config.is_configured


# --- cache key --------------------------------------------------------------

def test_doi_model_thi_doi_version():
    """version vào cache key — đổi model mà key không đổi thì cache trả bản dịch
    của model khác (§16)."""
    base = load_config("mock")
    a = ADAPTERS["mock"](base)
    b = ADAPTERS["mock"](ProviderConfig(**{**base.__dict__, "model": "mock-v2"}))
    assert a.version != b.version


# --- prompt -----------------------------------------------------------------

def test_prompt_mang_du_bon_rang_buoc(request_2_units):
    system, user = build_messages(request_2_units)

    assert "char_budget" in system, "thiếu ràng buộc độ dài (§7.2)"
    assert "es-ES" in system and "en-US" in system
    assert "GLOSSARY" in user and "Tool Reup" in user
    assert "Giọng thân mật." in user
    assert "KHÔNG dịch" in user, "ngữ cảnh phải nói rõ là không dịch"
    assert "Câu trước đó." in user

    payload = json.loads(user.split("đơn vị:\n", 1)[1])
    assert [p["idx"] for p in payload] == [0, 1]
    assert payload[0]["transcreate"] is True
    assert payload[0]["char_budget"] == 20


def test_over_budget_cho_phep_doi_chut():
    assert not over_budget("x" * 20, 20)
    assert not over_budget("x" * 22, 20), "dôi 10% thì Duration Fitting còn xử lý được"
    assert over_budget("x" * 30, 20)
    assert not over_budget("bất kỳ", None)


# --- parse kết quả ----------------------------------------------------------

def test_parse_go_duoc_markdown_fence():
    content = '```json\n[{"idx": 0, "text": "hola"}]\n```'
    assert _parse_translations(content, [0]) == {0: "hola"}


def test_parse_chap_nhan_dang_boc_trong_object():
    content = '{"translations": [{"idx": 0, "text": "hola"}]}'
    assert _parse_translations(content, [0]) == {0: "hola"}


def test_parse_thieu_don_vi_la_loi_cung():
    """Dịch thiếu segment mà cho qua thì video ra sẽ câm một đoạn (§15)."""
    content = '[{"idx": 0, "text": "hola"}]'
    with pytest.raises(ProviderError, match="thiếu bản dịch"):
        _parse_translations(content, [0, 1, 2])


def test_parse_json_hong_thi_retry_duoc():
    with pytest.raises(ProviderError) as exc:
        _parse_translations("không phải json", [0])
    assert exc.value.retryable, "model trả rác thì gọi lại thường là khỏi"


# --- mock provider ----------------------------------------------------------

def test_mock_ton_trong_char_budget(request_2_units):
    """Mock mô phỏng model được prompt tử tế: bám budget."""
    response = get_provider("mock").translate(request_2_units)

    assert set(response.translations) == {0, 1}
    for item in request_2_units.items:
        assert len(response.translations[item.idx]) <= item.char_budget


def test_mock_mo_phong_ban_dich_dai_hon_ban_goc():
    """Không có budget thì bản dịch phải dài ra — đó là gốc rễ của bài toán §7."""
    request = TranslationRequest(
        items=[TranslationItem(idx=0, text="A short English sentence.")],
        source_locale="en-US", target_locale="es-ES",
    )
    response = get_provider("mock").translate(request)
    assert len(response.translations[0]) > len(request.items[0].text)


def test_uoc_tinh_usage_truoc_khi_goi(request_2_units):
    """Dry-run chi phí trước khi batch chạy (§17.1)."""
    usage = get_provider("mock").estimate_usage(request_2_units)
    assert usage.tokens_in > 0 and usage.tokens_out > 0
    assert usage.characters == sum(len(i.text) for i in request_2_units.items)
