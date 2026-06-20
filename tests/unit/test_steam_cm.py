"""Тесты классификации результата входа в Steam CM.

Главное: транзиентные сетевые ошибки (TryAnotherCM=48 и пр.) НЕ должны
трактоваться как проблема пароля — иначе код удаляет валидные креды и виснет
в интерактивном ре-промпте (реальный баг на скане).
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from steam.enums import EResult  # noqa: E402

from app.steam.steam_cm import _cm_login_outcome  # noqa: E402


def test_outcome_ok():
    assert _cm_login_outcome(EResult.OK) == "ok"


def test_outcome_invalid_password_is_bad_password():
    assert _cm_login_outcome(EResult.InvalidPassword) == "bad_password"


def test_outcome_try_another_cm_is_transient():
    # EResult(48) — именно эта ошибка валила скан
    assert _cm_login_outcome(EResult.TryAnotherCM) == "transient"


def test_outcome_network_errors_are_transient():
    for r in (
        EResult.ServiceUnavailable,
        EResult.Timeout,
        EResult.NoConnection,
        EResult.ConnectFailed,
        EResult.RemoteDisconnect,
        EResult.Busy,
    ):
        assert _cm_login_outcome(r) == "transient", r


def test_outcome_account_error_is_skip_not_password():
    # Banned/Disabled — не пароль: креды не удаляем, но и в интерактив не идём
    assert _cm_login_outcome(EResult.Banned) == "skip"
