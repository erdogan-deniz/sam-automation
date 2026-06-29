"""Тесты Store API: подсчёт достижений (app/steam/store_api.py).

Критично (требование переделки каталога): отсутствие блока achievements →
None (unknown), 0 только если блок ЕСТЬ и total==0. Store ненадёжен —
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


def test_count_present_returns_total(monkeypatch) -> None:
    _patch_urlopen(
        monkeypatch,
        {"570": {"success": True, "data": {"achievements": {"total": 42}}}},
    )
    assert store.fetch_achievement_count(570) == 42


def test_count_zero_when_block_present_and_total_zero(monkeypatch) -> None:
    _patch_urlopen(
        monkeypatch,
        {"570": {"success": True, "data": {"achievements": {"total": 0}}}},
    )
    assert store.fetch_achievement_count(570) == 0


def test_missing_achievements_block_is_unknown_not_zero(monkeypatch) -> None:
    # success=True, но блока achievements нет → None (НЕ 0!). Корень бага v1.1.0.
    _patch_urlopen(
        monkeypatch,
        {"570": {"success": True, "data": {"name": "Game", "type": "game"}}},
    )
    assert store.fetch_achievement_count(570) is None


def test_unsuccessful_response_is_unknown(monkeypatch) -> None:
    # success=false (DLC/удалено/регион-лок) → None, не 0.
    _patch_urlopen(monkeypatch, {"570": {"success": False}})
    assert store.fetch_achievement_count(570) is None


def test_http_error_is_unknown(monkeypatch) -> None:
    err = urllib.error.HTTPError("u", 500, "err", {}, None)
    _patch_urlopen(monkeypatch, exc=err)
    assert store.fetch_achievement_count(570) is None


def test_rate_limit_returns_unknown_without_real_sleep(monkeypatch) -> None:
    monkeypatch.setattr(store.time, "sleep", lambda *_a: None)
    err = urllib.error.HTTPError("u", 429, "rate", {}, None)
    _patch_urlopen(monkeypatch, exc=err)
    assert store.fetch_achievement_count(570) is None


def test_network_error_is_unknown(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, exc=OSError("boom"))
    assert store.fetch_achievement_count(570) is None
