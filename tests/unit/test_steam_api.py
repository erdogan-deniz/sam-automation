"""Тесты поведения app/steam/steam_api.py (форма ответа + 429-ретрай).

Сетевое-хардненинг _api_get (OSError/HTTPException/не-JSON) покрыт в
test_network_hardening.py; здесь — фильтр битых записей, ограниченный ретрай
на HTTP 429 и honest-warning при game_count>0 с пустым списком games.
"""

from __future__ import annotations

import email.message
import json
import logging
import urllib.error

import pytest

from app.steam import steam_api

_VALID_ID = "76561197960265728"


class _JsonResp:
    """Контекст-менеджер ответа urlopen с валидным JSON-телом."""

    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _JsonResp:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _http_error_429(
    retry_after: object | None = None,
) -> urllib.error.HTTPError:
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "https://api.steampowered.com/x", 429, "Too Many Requests", hdrs, None
    )


# ── C1: фильтр записей без валидного appid ─────────────────────────────────


def test_fetch_owned_games_filters_records_without_appid(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    payload = {
        "response": {
            "games": [
                {"appid": 10, "name": "A"},
                {"name": "нет appid"},
                {"appid": None, "name": "appid=None"},
                {"appid": 730, "name": "B"},
            ]
        }
    }
    monkeypatch.setattr(steam_api, "_api_get", lambda url: payload)

    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        games = steam_api.fetch_owned_games("key", _VALID_ID)

    # Одна битая запись не роняет источник (потребитель делает g["appid"]).
    assert [g["appid"] for g in games] == [10, 730]
    assert all(g.get("appid") is not None for g in games)


# ── C2: ограниченный ретрай на HTTP 429 с уважением Retry-After ─────────────


def test_api_get_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_urlopen(*_a: object, **_k: object) -> _JsonResp:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error_429(retry_after=2)
        return _JsonResp({"ok": True})

    sleeps: list[float] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    result = steam_api._api_get("https://api.steampowered.com/x")

    assert result == {"ok": True}
    assert calls["n"] == 2  # первый 429, второй успех
    assert sleeps == [2.0]  # уважил Retry-After


def test_api_get_429_bounded_retry_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Постоянный 429 → ограниченное число попыток, затем ошибка (не вечно)."""
    calls = {"n": 0}

    def fake_urlopen(*_a: object, **_k: object) -> _JsonResp:
        calls["n"] += 1
        raise _http_error_429(retry_after=1)

    sleeps: list[float] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    with pytest.raises(steam_api._RateLimitError):
        steam_api._api_get("https://api.steampowered.com/x")

    assert calls["n"] == steam_api._RATE_LIMIT_ATTEMPTS
    assert len(sleeps) == steam_api._RATE_LIMIT_ATTEMPTS - 1


def test_api_get_caps_excessive_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Злой Retry-After (часы) капается разумным потолком, не висим вечно."""
    calls = {"n": 0}

    def fake_urlopen(*_a: object, **_k: object) -> _JsonResp:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error_429(retry_after=9999)
        return _JsonResp({"ok": True})

    sleeps: list[float] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    steam_api._api_get("https://api.steampowered.com/x")

    assert sleeps
    assert sleeps[0] <= steam_api._RATE_LIMIT_DELAY_CAP


def test_api_get_429_without_retry_after_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 без заголовка Retry-After → дефолтная пауза, ретрай всё равно есть."""
    calls = {"n": 0}

    def fake_urlopen(*_a: object, **_k: object) -> _JsonResp:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error_429(retry_after=None)
        return _JsonResp({"ok": True})

    sleeps: list[float] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    result = steam_api._api_get("https://api.steampowered.com/x")

    assert result == {"ok": True}
    assert sleeps == [steam_api._RATE_LIMIT_DELAY]


# ── C3: отсутствие response/games и game_count>0 при пустом games ───────────


def test_fetch_owned_games_missing_response_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(steam_api, "_api_get", lambda url: {})
    assert steam_api.fetch_owned_games("key", _VALID_ID) == []


def test_fetch_owned_games_missing_games_key_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        steam_api, "_api_get", lambda url: {"response": {"game_count": 0}}
    )
    assert steam_api.fetch_owned_games("key", _VALID_ID) == []


def test_fetch_owned_games_warns_on_count_positive_empty_games(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        steam_api,
        "_api_get",
        lambda url: {"response": {"game_count": 5, "games": []}},
    )
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        result = steam_api.fetch_owned_games("key", _VALID_ID)

    assert result == []
    assert any("game_count" in r.getMessage() for r in caplog.records)
