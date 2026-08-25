"""Mã hoá OAuth token (§18.1, Phase 5) — services/crypto.py."""

from __future__ import annotations

import pytest

from services.crypto import decrypt_token, encrypt_token


def test_ma_hoa_roi_giai_ma_ra_dung_gia_tri_goc():
    original = "ya29.a0AfH6SMC_fake_access_token"
    ciphertext = encrypt_token(original)
    assert ciphertext != original, "phải thực sự mã hoá, không lưu plaintext"
    assert decrypt_token(ciphertext) == original


def test_ciphertext_sai_khong_giai_ma_duoc():
    with pytest.raises(ValueError, match="không giải mã được"):
        decrypt_token("rác-không-phải-fernet-token")
