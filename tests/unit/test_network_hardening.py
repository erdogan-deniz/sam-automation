"""Устойчивость сетевых запросов к OSError/http.client.HTTPException.

Тот же класс бага, что чинили в card_checker._fetch_page (PR #13): код ловил
ТОЛЬКО urllib HTTPError/URLError, а RemoteDisconnected (⊂OSError) при редиректе
и IncompleteRead (⊂HTTPException) при обрыве тела ответа проходили мимо и
роняли весь прогон вместо чистой обработки.

Здесь — те же дыры в app/steam/steam_api._api_get и app/validator._check_steam_api.
"""

from __future__ import annotations

import http.client

import pytest

from app import validator
from app.config import Config
from app.steam import steam_api


class _ReadBoomResp:
    """Контекст-менеджер ответа, чей .read() кидает IncompleteRead."""

    def __enter__(self) -> _ReadBoomResp:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def read(self) -> bytes:
        raise http.client.IncompleteRead(b"partial")


def test_api_get_wraps_incomplete_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """IncompleteRead при resp.read() → RuntimeError (ловится ретраем/caller)."""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _ReadBoomResp()
    )
    with pytest.raises(RuntimeError):
        steam_api._api_get("https://api.steampowered.com/x")


def test_api_get_wraps_remote_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RemoteDisconnected на самом urlopen → RuntimeError, не сырое исключение."""

    def boom(*_a: object, **_k: object) -> object:
        raise http.client.RemoteDisconnected("closed")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError):
        steam_api._api_get("https://api.steampowered.com/x")


def test_validator_steam_api_survives_incomplete_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """validate() обещает 'никогда не бросает' — IncompleteRead → список ошибок."""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _ReadBoomResp()
    )
    cfg = Config()
    cfg.steam_api_key = "x"
    cfg.steam_id = "76561190000000000"

    errs = validator._check_steam_api(cfg)

    assert errs  # вернул сообщение об ошибке, а не упал трейсбеком
    assert any("Steam API" in e for e in errs)
