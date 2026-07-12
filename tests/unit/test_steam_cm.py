"""Тесты классификации результата входа в Steam CM.

Главное: транзиентные сетевые ошибки (TryAnotherCM=48 и пр.) НЕ должны
трактоваться как проблема пароля — иначе код удаляет валидные креды и виснет
в интерактивном ре-промпте (реальный баг на скане).
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from steam.enums import EResult  # noqa: E402

from app.steam.steam_cm import (  # noqa: E402
    _cm_login_outcome,
    _password_failure_action,
    _should_clear_session_after_rsa,
)


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


# ── _password_failure_action: маршрутизация после неуспешного логина ───────


def test_password_failure_invalid_password_tries_rsa():
    # InvalidPassword мог отвергнуть ВАЛИДНЫЕ креды modern-auth аккаунта →
    # RSA-путь ДО удаления кредов.
    assert _password_failure_action(EResult.InvalidPassword) == "try_rsa"


def test_password_failure_transient_skips_cm():
    # Сетевая (TryAnotherCM) — креды сохранить, CM пропустить, не RSA.
    assert _password_failure_action(EResult.TryAnotherCM) == "skip_cm"


def test_password_failure_account_error_skips_cm():
    # Ошибка аккаунта (не пароль) → пропуск CM, креды сохранить.
    assert _password_failure_action(EResult.Banned) == "skip_cm"


# ── _should_clear_session_after_rsa: транзиент не стирает валидные креды ─────


def test_rsa_failure_never_clears_session():
    # Ни один исход _rsa_jwt_login не является надёжным «неверный пароль»:
    # None неразличимо (сеть ИЛИ отказ поллинга), а конкретный EResult приходит
    # из _cm_login_with_jwt, который выполняется УЖЕ имея валидный токен (пароль
    # принят). Стирать необратимые креды на этом основании нельзя — инвариант
    # «transient не удаляет креды».
    for r in (
        None,
        EResult.InvalidPassword,
        EResult.TryAnotherCM,
        EResult.ServiceUnavailable,
        EResult.Timeout,
    ):
        assert _should_clear_session_after_rsa(r) is False, r


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


# ── read_steam_cm_app_ids: disconnect в try/finally (утечка gevent) ─────────


import pytest  # noqa: E402


class _FakeSteamClient:
    """Двойник SteamClient: считает disconnect(), остальное — no-op."""

    def __init__(self, *a, **k) -> None:
        self.disconnect_calls = 0

    def set_credential_location(self, *a, **k) -> None:
        pass

    def once(self, *a, **k) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnect_calls += 1


def test_read_cm_disconnects_on_exception(monkeypatch):
    # EOFError/любое исключение «в середине» (cron без stdin) НЕ должно оставлять
    # gevent-соединение висеть: disconnect обязателен через finally.
    created: dict = {}

    def _make(*a, **k):
        c = _FakeSteamClient()
        created["client"] = c
        return c

    monkeypatch.setattr("steam.client.SteamClient", _make)
    monkeypatch.setattr(steam_cm, "_steam_api_reachable", lambda *a, **k: True)

    def _boom(*a, **k):
        raise EOFError("нет stdin")

    monkeypatch.setattr(steam_cm, "_load_session", _boom)

    with pytest.raises(EOFError):
        steam_cm.read_steam_cm_app_ids("C:/steam", "user", interactive=True)

    assert created["client"].disconnect_calls >= 1


# ── _login_saved_with_2fa: авто-TOTP с откатом на ручной ввод ──────────────


def test_2fa_auto_ok_no_manual():
    # Верный авто-код → OK, ручной ввод не запрашивается.
    calls: list[str] = []

    def do_login(code):
        calls.append(code)
        return EResult.OK

    def prompt():
        raise AssertionError("ручной ввод не должен вызываться")

    result = steam_cm._login_saved_with_2fa(
        do_login, "AUTO", prompt, EResult.OK
    )
    assert result == EResult.OK
    assert calls == ["AUTO"]


def test_2fa_auto_wrong_falls_back_to_manual():
    # Неверный авто-код (перекос часов) → откат на ручной ввод, затем OK.
    calls: list[str] = []

    def do_login(code):
        calls.append(code)
        return EResult.OK if code == "MANUAL" else EResult.TwoFactorCodeMismatch

    result = steam_cm._login_saved_with_2fa(
        do_login, "AUTO", lambda: "MANUAL", EResult.OK
    )
    assert result == EResult.OK
    assert calls == ["AUTO", "MANUAL"]  # авто первым, потом ручной


def test_2fa_no_shared_uses_manual():
    # Нет shared_secret (auto_code None) → сразу ручной ввод.
    calls: list[str] = []

    def do_login(code):
        calls.append(code)
        return EResult.OK

    result = steam_cm._login_saved_with_2fa(
        do_login, None, lambda: "TYPED", EResult.OK
    )
    assert result == EResult.OK
    assert calls == ["TYPED"]


def test_2fa_timeout_returns_none_immediately():
    # do_login вернул None (таймаут) → возврат None сразу, без ретрая.
    calls: list[str] = []

    def do_login(code):
        calls.append(code)
        return None

    result = steam_cm._login_saved_with_2fa(
        do_login, "AUTO", lambda: "MANUAL", EResult.OK
    )
    assert result is None
    assert calls == ["AUTO"]


def test_2fa_all_wrong_returns_last_result():
    # Все попытки неверны → возврат последнего неуспеха (не виснем).
    calls: list[str] = []

    def do_login(code):
        calls.append(code)
        return EResult.TwoFactorCodeMismatch

    result = steam_cm._login_saved_with_2fa(
        do_login, "AUTO", lambda: "MANUAL", EResult.OK
    )
    assert result == EResult.TwoFactorCodeMismatch
    assert calls == ["AUTO", "MANUAL"]
