"""Mã hoá OAuth token trước khi lưu DB (§18.1: "OAuth token mã hoá, có cơ chế
revoke/refresh") — dùng cho `PlatformAccount.access_token`/`refresh_token`
(Phase 5, §20).

`Fernet` (đối xứng, AES128-CBC + HMAC) là đủ ở đây: khoá chỉ cần giải mã lại
được bởi chính backend đã mã hoá, không phải trao đổi khoá với bên thứ ba.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings

log = logging.getLogger("vla.crypto")


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.token_encryption_key
    if not key:
        # Sinh khoá TẠM cho dev/test — mất khi restart process, nghĩa là
        # PlatformAccount cũ sẽ không giải mã lại được. KHÔNG dùng nhánh này
        # ở môi trường có token thật (set VLA_TOKEN_ENCRYPTION_KEY).
        log.warning(
            "VLA_TOKEN_ENCRYPTION_KEY chưa đặt — dùng khoá mã hoá TẠM, mất khi "
            "restart process. Chỉ chấp nhận được ở dev/test với token giả "
            "(mock provider). Đặt VLA_TOKEN_ENCRYPTION_KEY trước khi có token "
            "OAuth thật (services/publishing/)."
        )
        key = Fernet.generate_key().decode()
    return Fernet(key.encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "không giải mã được token — sai VLA_TOKEN_ENCRYPTION_KEY hoặc "
            "token được mã hoá bằng khoá TẠM đã mất (restart process)"
        ) from exc
