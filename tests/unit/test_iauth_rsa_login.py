"""Тесты оркестрации современного RSA-пути входа в CM (app/auth/iauth_service.py).

_rsa_jwt_login связывает _jwt_web_cookies (RSA → refresh_token) и
_cm_login_with_jwt (ClientLogon по refresh_token). Здесь мокаются ТОЛЬКО эти
листовые коллабораторы и кэш-ридеры — проверяется собственная логика ветвления
функций (когда CM-логон вызывается, а когда нет; что в него передаётся; какой
кэш-файл читается под scope), а НЕ сетевой протокол Steam.

Scope токена (SteamClient vs WebBrowser) — корень бага AccessDenied: client-scope
refresh_token и веб-токен кэшируются в РАЗНЫЕ файлы.
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import app.auth.iauth_service as iauth  # noqa: E402
from app.auth._constants import (  # noqa: E402
    _JWT_REFRESH_CLIENT_FILE,
    _JWT_REFRESH_FILE,
)


class _FakeClient:
    """Минимальный двойник SteamClient: считает disconnect()."""

    def __init__(self) -> None:
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1


def _must_not_call(*_a, **_k):
    raise AssertionError("не должно вызываться в этой ветке")


# ── _rsa_jwt_login: оркестрация RSA → refresh_token → CM-логон ──


def test_rsa_login_returns_none_when_jwt_web_cookies_fails(monkeypatch):
    # RSA-этап не дал токена (None) → CM-логон НЕ вызывается, результат None.
    monkeypatch.setattr(iauth, "_jwt_web_cookies", lambda *_a, **_k: None)
    monkeypatch.setattr(iauth, "_cm_login_with_jwt", _must_not_call)

    assert iauth._rsa_jwt_login(_FakeClient(), "user", "pass", 30) is None


def test_rsa_login_returns_none_when_refresh_token_missing(monkeypatch):
    # Вернулся dict БЕЗ refresh_token (например только веб-кука) → CM-логон по
    # client-scope невозможен → None, CM не вызывается.
    monkeypatch.setattr(
        iauth,
        "_jwt_web_cookies",
        lambda *_a, **_k: {"steamLoginSecure": "x", "refresh_token": ""},
    )
    monkeypatch.setattr(iauth, "_cm_login_with_jwt", _must_not_call)

    assert iauth._rsa_jwt_login(_FakeClient(), "user", "pass", 30) is None


def test_rsa_login_forwards_refresh_token_to_cm_login(monkeypatch):
    # Есть refresh_token → его передают в _cm_login_with_jwt, результат CM
    # пробрасывается наружу, перед логоном делается disconnect().
    monkeypatch.setattr(
        iauth, "_jwt_web_cookies", lambda *_a, **_k: {"refresh_token": "RT-123"}
    )
    captured: dict = {}

    def _fake_cm(client, username, refresh_token, timeout):
        captured.update(
            username=username, refresh_token=refresh_token, timeout=timeout
        )
        return "CM_OK"

    monkeypatch.setattr(iauth, "_cm_login_with_jwt", _fake_cm)
    client = _FakeClient()

    result = iauth._rsa_jwt_login(client, "user", "pass", 30)

    assert result == "CM_OK"
    assert captured == {
        "username": "user",
        "refresh_token": "RT-123",
        "timeout": 30,
    }
    assert client.disconnect_calls == 1


def test_rsa_login_requests_steamclient_scope_token(monkeypatch):
    # for_steam_client=True обязателен — иначе CM отвергнет веб-токен (AccessDenied).
    captured: dict = {}

    def _fake_web(username, password, *, for_steam_client=False, _outcome=None):
        captured["for_steam_client"] = for_steam_client
        return None

    monkeypatch.setattr(iauth, "_jwt_web_cookies", _fake_web)

    iauth._rsa_jwt_login(_FakeClient(), "user", "pass", 30)

    assert captured["for_steam_client"] is True


def test_rsa_login_returns_invalid_password_on_definitive_rejection(
    monkeypatch,
):
    # Современный Begin достоверно отверг RSA-пароль (записал InvalidPassword в
    # _outcome) → _rsa_jwt_login пробрасывает EResult.InvalidPassword (а не None),
    # чтобы вызывающий мог стереть сессию и переспросить.
    from steam.enums import EResult

    def _fake_web(username, password, *, for_steam_client=False, _outcome=None):
        if _outcome is not None:
            _outcome.append(EResult.InvalidPassword)
        return None

    monkeypatch.setattr(iauth, "_jwt_web_cookies", _fake_web)
    monkeypatch.setattr(iauth, "_cm_login_with_jwt", _must_not_call)

    result = iauth._rsa_jwt_login(_FakeClient(), "user", "pass", 30)

    assert result == EResult.InvalidPassword


def test_rsa_login_returns_none_on_transient_without_verdict(monkeypatch):
    # Сеть/таймаут: cookies=None, но _outcome пуст (Begin не дошёл до вердикта) →
    # НЕ выдаём InvalidPassword, возвращаем None (креды выше не трогаются).
    def _fake_web(username, password, *, for_steam_client=False, _outcome=None):
        return None  # ничего не пишет в _outcome

    monkeypatch.setattr(iauth, "_jwt_web_cookies", _fake_web)
    monkeypatch.setattr(iauth, "_cm_login_with_jwt", _must_not_call)

    assert iauth._rsa_jwt_login(_FakeClient(), "user", "pass", 30) is None


def test_rsa_login_swallows_invalid_password_from_cm_token_stage(monkeypatch):
    # token-этап (_cm_login_with_jwt по refresh_token) НЕ несёт вердикта по
    # паролю (пароля в ClientLogon нет). Если CM вернёт InvalidPassword, он НЕ
    # должен просочиться как authoritative-сигнал в решение о стирании кред —
    # _rsa_jwt_login нормализует его в None (единственный источник вердикта —
    # _outcome от Begin-пути).
    from steam.enums import EResult

    monkeypatch.setattr(
        iauth, "_jwt_web_cookies", lambda *_a, **_k: {"refresh_token": "RT"}
    )
    monkeypatch.setattr(
        iauth, "_cm_login_with_jwt", lambda *_a, **_k: EResult.InvalidPassword
    )

    assert iauth._rsa_jwt_login(_FakeClient(), "user", "pass", 30) is None


# ── _jwt_web_cookies: короткое замыкание из кэша по scope ──


def test_jwt_web_cookies_steamclient_reads_client_cache_file(monkeypatch):
    # client-scope читает СЫРОЙ refresh_token из CLIENT-кэша и возвращает его
    # сразу, без сети. Веб-деривацию не трогает.
    captured: dict = {}

    def _fake_load(path):
        captured["path"] = path
        return "RAW-RT"

    monkeypatch.setattr(iauth, "_load_refresh_token", _fake_load)
    monkeypatch.setattr(iauth, "_jwt_from_refresh_token", _must_not_call)

    result = iauth._jwt_web_cookies("user", "pass", for_steam_client=True)

    assert result == {"refresh_token": "RAW-RT"}
    assert captured["path"] == _JWT_REFRESH_CLIENT_FILE


def test_jwt_web_cookies_web_scope_reads_web_cache_file(monkeypatch):
    # web-scope деривует access_token из WEB-кэша (другой файл, другой scope).
    captured: dict = {}

    def _fake_from_rt(path):
        captured["path"] = path
        return {"steamLoginSecure": "sid||tok"}

    monkeypatch.setattr(iauth, "_jwt_from_refresh_token", _fake_from_rt)
    monkeypatch.setattr(iauth, "_load_refresh_token", _must_not_call)

    result = iauth._jwt_web_cookies("user", "pass", for_steam_client=False)

    assert result == {"steamLoginSecure": "sid||tok"}
    assert captured["path"] == _JWT_REFRESH_FILE
