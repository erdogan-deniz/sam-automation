"""Тесты Steam Guard TOTP (app/auth/totp.py)."""

from __future__ import annotations

import base64

import pytest

from app.auth import totp
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


# Эталон — steam.guard.generate_twofactor_code_for_time (библиотека steam),
# секрет base64(b"12345678901234567890"). До 22.10.2026 код собирался задом
# наперёд, и каждый авто-код Steam Guard был неверен (B-21 #4).
@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [(0, "GG5F5"), (1_700_000_000, "R87JJ"), (1_792_600_000, "8R3M9")],
)
def test_code_matches_reference_vectors(
    monkeypatch: pytest.MonkeyPatch, timestamp: int, expected: str
) -> None:
    monkeypatch.setattr(totp.time, "time", lambda: float(timestamp))
    assert _compute_steam_totp("MTIzNDU2Nzg5MDEyMzQ1Njc4OTA=") == expected
