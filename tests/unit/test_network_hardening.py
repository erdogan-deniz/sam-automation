"""Устойчивость сетевых запросов к OSError/http.client.HTTPException.

Тот же класс бага, что чинили в card_checker._fetch_page (PR #13): код ловил
ТОЛЬКО urllib HTTPError/URLError, а RemoteDisconnected (⊂OSError) при редиректе
и IncompleteRead (⊂HTTPException) при обрыве тела ответа проходили мимо и
роняли весь прогон вместо чистой обработки.

Здесь — те же дыры в app/steam/steam_api._api_get и app/validator._check_steam_api.
"""

from __future__ import annotations

import http.client
from pathlib import Path

import pytest

from app import validator
from app.config import Config
from app.sam import sam_downloader
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


def test_fetch_latest_release_wraps_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RemoteDisconnected при запросе релиза SAM → RuntimeError, не сырой краш."""

    def boom(*_a: object, **_k: object) -> object:
        raise http.client.RemoteDisconnected("closed")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError):
        sam_downloader._fetch_latest_release()


def test_download_sam_zip_fetch_wraps_network_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Сетевой сбой при скачивании zip → RuntimeError (caller farm/boost ловит),
    а не сырой трейсбек на первом запуске SAM без сети."""
    release = {
        "tag_name": "v1.0",
        "assets": [
            {"name": "sam.zip", "browser_download_url": "http://x/sam.zip"}
        ],
    }

    def boom(*_a: object, **_k: object) -> object:
        raise ConnectionResetError("reset")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError):
        sam_downloader.download_sam(str(tmp_path), release=release)


class _NonJsonResp:
    """HTTP 200 с НЕ-JSON телом (Cloudflare/капча/страница логина)."""

    def __enter__(self) -> _NonJsonResp:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def read(self) -> bytes:
        return b"<html>Please log in</html>"


def test_api_get_wraps_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 с не-JSON телом → RuntimeError, а не сырой JSONDecodeError."""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _NonJsonResp()
    )
    with pytest.raises(RuntimeError):
        steam_api._api_get("https://api.steampowered.com/x")


def test_validator_survives_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate() «никогда не бросает»: не-JSON ответ → список ошибок, не краш."""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _NonJsonResp()
    )
    cfg = Config()
    cfg.steam_api_key = "x"
    cfg.steam_id = "76561190000000000"

    errs = validator._check_steam_api(cfg)

    assert errs  # вернул сообщение, а не упал JSONDecodeError
    assert any("Steam API" in e for e in errs)
