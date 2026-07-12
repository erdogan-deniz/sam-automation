"""Тесты app.steam.steam_id.resolve_steam_id.

scan теперь резолвит Steam ID до валидации (как boost/cards). Проверяем все
ветки: числовой ID64 и /profiles/<17> — без сети; vanity name и /id/<v> —
через ResolveVanityURL; неуспех резолва → RuntimeError.
"""

from __future__ import annotations

import pytest

import app.steam.steam_id as steam_id
from app.steam import resolve_steam_id

_ID64 = "76561197960287930"


def test_numeric_id64_passthrough_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(url: str) -> dict:
        raise AssertionError("network must not be called for numeric ID64")

    monkeypatch.setattr(steam_id, "_api_get", _boom)
    assert resolve_steam_id("key", _ID64) == _ID64


def test_profiles_url_extracts_id_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(url: str) -> dict:
        raise AssertionError("network must not be called for /profiles/ URL")

    monkeypatch.setattr(steam_id, "_api_get", _boom)
    url = f"https://steamcommunity.com/profiles/{_ID64}"
    assert resolve_steam_id("key", url) == _ID64


def test_id_url_resolves_vanity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, str] = {}

    def _fake(url: str) -> dict:
        calls["url"] = url
        return {"response": {"success": 1, "steamid": _ID64}}

    monkeypatch.setattr(steam_id, "_api_get", _fake)
    url = "https://steamcommunity.com/id/gabelogannewell"
    assert resolve_steam_id("key", url) == _ID64
    assert "gabelogannewell" in calls["url"]


def test_bare_vanity_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        steam_id,
        "_api_get",
        lambda url: {"response": {"success": 1, "steamid": _ID64}},
    )
    assert resolve_steam_id("key", "gabelogannewell") == _ID64


def test_vanity_failure_raises_runtimeerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        steam_id,
        "_api_get",
        lambda url: {"response": {"success": 42, "message": "no match"}},
    )
    with pytest.raises(RuntimeError, match="vanity"):
        resolve_steam_id("key", "nonexistent-vanity")
