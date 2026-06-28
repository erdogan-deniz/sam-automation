"""Тесты классификации Steam Guard (EAuthSessionGuardType) в RSA-пути.

Баг: confirmation-цикл _jwt_web_cookies трактовал тип 4 (DeviceConfirmation —
подтверждение в приложении, КОДА НЕТ) как TOTP, а реальный тип 3 (DeviceCode —
TOTP мобильного аутентификатора) молча игнорировал (else: continue). Для
аккаунта с мобильным аутентификатором это давало тихий провал и 0 игр по CM.

Значения enum проверены по installed proto steammessages_auth_pb2:
  0 Unknown, 1 None, 2 EmailCode, 3 DeviceCode, 4 DeviceConfirmation,
  5 EmailConfirmation, 6 MachineToken.
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.auth.iauth_service import _guard_action  # noqa: E402


def test_email_code_needs_code():
    # EmailCode (2) — код приходит на почту, его надо ввести.
    assert _guard_action(2) == "email_code"


def test_device_code_is_totp():
    # DeviceCode (3) — TOTP мобильного аутентификатора. РАНЬШЕ игнорировался.
    assert _guard_action(3) == "device_code"


def test_device_confirmation_has_no_code():
    # DeviceConfirmation (4) — подтверждение в приложении, кода НЕТ → только поллинг.
    # РАНЬШЕ ошибочно трактовался как TOTP.
    assert _guard_action(4) == "confirm"


def test_email_confirmation_has_no_code():
    # EmailConfirmation (5) — подтверждение по ссылке из email, кода нет.
    assert _guard_action(5) == "confirm"


def test_other_guard_types_are_skipped():
    # Unknown/None/MachineToken — нечего делать в коде подтверждения.
    for t in (0, 1, 6):
        assert _guard_action(t) == "skip", t
