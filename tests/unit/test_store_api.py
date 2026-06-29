"""Тесты Store API: информация о достижениях (app/steam/store_api.py).

fetch_achievement_info различает ТРИ исхода:
  - total=N, responded=True   — блок achievements есть (N>=0);
  - total=None, responded=True — Store ОТВЕТИЛ, но блока нет (data:[]/
    success=false): стабильное «нет данных» → каталог store_empty;
  - total=None, responded=False — транзиентная ошибка сети/HTTP → ретрай.

Критично (урок отката v1.1.0): отсутствие блока НЕ равно «0 достижений» —
playtest/демо/регион-лок отдают пустой блок даже при реальных достижениях.
"""

from __future__ import annotations

import json
import urllib.error

import app.steam.store_api as store


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False


def _patch_urlopen(monkeypatch, payload=None, exc=None) -> None:
    def _fake(_req, timeout=10):
        if exc is not None:
            raise exc
        return _FakeResp(payload)

    monkeypatch.setattr(store.urllib.request, "urlopen", _fake)


def test_count_present_returns_total_and_responded(monkeypatch) -> None:
    _patch_urlopen(
        monkeypatch,
        {"570": {"success": True, "data": {"achievements": {"total": 42}}}},
    )
    info = store.fetch_achievement_info(570)
    assert info.total == 42
    assert info.responded is True


def test_count_zero_when_block_present_and_total_zero(monkeypatch) -> None:
    _patch_urlopen(
        monkeypatch,
        {"570": {"success": True, "data": {"achievements": {"total": 0}}}},
    )
    info = store.fetch_achievement_info(570)
    assert info.total == 0
    assert info.responded is True


def test_missing_block_is_responded_empty_not_zero(monkeypatch) -> None:
    # success=True, но блока achievements нет → total=None, responded=True.
    _patch_urlopen(
        monkeypatch,
        {"570": {"success": True, "data": {"name": "Game", "type": "game"}}},
    )
    info = store.fetch_achievement_info(570)
    assert info.total is None
    assert info.responded is True


def test_empty_data_list_is_responded_empty(monkeypatch) -> None:
    # Реальный кейс appid 10 (CS): data:[] → Store ответил, данных нет.
    _patch_urlopen(monkeypatch, {"10": {"success": True, "data": []}})
    info = store.fetch_achievement_info(10)
    assert info.total is None
    assert info.responded is True


def test_unsuccessful_response_is_responded_empty(monkeypatch) -> None:
    # success=false (DLC/удалено/регион) — Store ответил, страницы нет.
    _patch_urlopen(monkeypatch, {"570": {"success": False}})
    info = store.fetch_achievement_info(570)
    assert info.total is None
    assert info.responded is True


def test_http_error_is_transient_not_responded(monkeypatch) -> None:
    err = urllib.error.HTTPError("u", 500, "err", {}, None)
    _patch_urlopen(monkeypatch, exc=err)
    info = store.fetch_achievement_info(570)
    assert info.total is None
    assert info.responded is False


def test_rate_limit_is_transient_without_real_sleep(monkeypatch) -> None:
    monkeypatch.setattr(store.time, "sleep", lambda *_a: None)
    err = urllib.error.HTTPError("u", 429, "rate", {}, None)
    _patch_urlopen(monkeypatch, exc=err)
    info = store.fetch_achievement_info(570)
    assert info.responded is False


def test_network_error_is_transient(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, exc=OSError("boom"))
    info = store.fetch_achievement_info(570)
    assert info.total is None
    assert info.responded is False
