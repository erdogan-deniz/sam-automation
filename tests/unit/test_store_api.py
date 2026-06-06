"""Тесты для app/steam/store_api.py — парсинг ответов Store API appdetails."""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from app.steam import store_api


class _FakeResp:
    """Минимальный контекст-менеджер, имитирующий ответ urlopen."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    def fake(_req: object, timeout: float = 0) -> _FakeResp:
        return _FakeResp(payload)

    monkeypatch.setattr(store_api.urllib.request, "urlopen", fake)


def test_count_with_achievements(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(
        monkeypatch,
        {"730": {"success": True, "data": {"achievements": {"total": 167}}}},
    )
    assert store_api.fetch_achievement_count(730) == 167


def test_count_in_store_without_achievements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Игра есть в Store, но блока achievements нет → 0 (→ without)."""
    _patch_urlopen(monkeypatch, {"440": {"success": True, "data": {}}})
    assert store_api.fetch_achievement_count(440) == 0


def test_count_not_in_store_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Приложения нет в Store (DLC/удалено) → None (не классифицируем)."""
    _patch_urlopen(monkeypatch, {"999": {"success": False}})
    assert store_api.fetch_achievement_count(999) is None


def test_count_http_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_req: object, timeout: float = 0) -> None:
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(store_api.urllib.request, "urlopen", fake)
    assert store_api.fetch_achievement_count(123) is None
