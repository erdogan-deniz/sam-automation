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


# ── _should_try_rsa_fallback: legacy login даёт InvalidPassword на верных ──
# кредах для аккаунтов, переведённых Steam на современный auth. Тогда нужно
# попробовать RSA-путь (_jwt_web_cookies), прежде чем считать пароль неверным.


from app.steam.steam_cm import _should_try_rsa_fallback  # noqa: E402


def test_rsa_fallback_on_invalid_password():
    # InvalidPassword от legacy login ≠ точно неверный пароль: официальный
    # клиент с теми же кредами входит → пробуем современный RSA-путь.
    assert _should_try_rsa_fallback(EResult.InvalidPassword) is True


def test_no_rsa_fallback_on_ok():
    assert _should_try_rsa_fallback(EResult.OK) is False


def test_no_rsa_fallback_on_transient():
    # Транзиентные — это сеть, RSA-путь упрётся в ту же сеть, не пробуем.
    for r in (
        EResult.TryAnotherCM,
        EResult.ServiceUnavailable,
        EResult.Timeout,
    ):
        assert _should_try_rsa_fallback(r) is False, r


def test_no_rsa_fallback_on_account_error():
    # Banned/2FA — пароль не при чём, RSA не поможет.
    for r in (EResult.Banned, EResult.AccountLoginDeniedNeedTwoFactor):
        assert _should_try_rsa_fallback(r) is False, r


# ── _steam_api_reachable: пре-чек доступности перед интерактивом ───────────


from app.steam import steam_cm  # noqa: E402


def test_api_reachable_true(monkeypatch):
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        steam_cm.urllib.request, "urlopen", lambda *a, **k: _Resp()
    )
    assert steam_cm._steam_api_reachable(timeout=1, attempts=1) is True


def test_api_reachable_false_on_error(monkeypatch):
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise OSError("read timed out")

    monkeypatch.setattr(steam_cm.urllib.request, "urlopen", boom)
    assert steam_cm._steam_api_reachable(timeout=0.01, attempts=2) is False
    assert calls["n"] == 2  # обе попытки сделаны
