"""Тесты Steam Guard TOTP (app/auth/totp.py)."""

from __future__ import annotations

import base64

from app.auth.totp import _compute_steam_totp

_STEAM_ALPHABET = "23456789BCDFGHJKMNPQRTVWXY"


def test_valid_secret_returns_5char_code_from_steam_alphabet() -> None:
    secret = base64.b64encode(b"0123456789abcdefghij").decode()  # 20 байт
    code = _compute_steam_totp(secret)
    assert len(code) == 5
    assert all(ch in _STEAM_ALPHABET for ch in code)


def test_malformed_base64_secret_returns_empty_not_raises() -> None:
    # Кривой/повреждённый shared_secret не должен ронять авторизацию:
    # вызывающий код трактует "" как «нет авто-кода» и спросит 2FA вручную.
    assert _compute_steam_totp("notvalidbase64") == ""
