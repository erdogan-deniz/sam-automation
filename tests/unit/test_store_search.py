"""Тесты пагинации store search (app/steam/store_search.py).

Перенесено из test_free_games_discovery.py (2026-09-12) вместе с вынесением
search_page/collect_category в общий модуль — переиспользуется app/demos/.
"""

from __future__ import annotations

import email.message
import json
import urllib.error

from app.steam import store_search


class _FakeResp:
    """Контекст-менеджер ответа urlopen с валидным JSON-телом."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_error_429() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://store.steampowered.com/x",
        429,
        "Too Many Requests",
        email.message.Message(),
        None,
    )


def _page_payload(appids: list[int], total_count: int) -> dict:
    html = "".join(f'<a data-ds-appid="{a}">x</a>' for a in appids)
    return {
        "success": 1,
        "results_html": html,
        "total_count": total_count,
        "start": 0,
    }


def test_search_page_parses_appids_and_total_count(monkeypatch):
    monkeypatch.setattr(
        store_search.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(_page_payload([730, 570], 19691)),
    )
    appids, total = store_search.search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == [730, 570]
    assert total == 19691


def test_search_page_maxprice_free_only_when_requested(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        return _FakeResp(_page_payload([], 0))

    monkeypatch.setattr(store_search.urllib.request, "urlopen", fake_urlopen)

    store_search.search_page(
        category1=10, start=0, count=100, maxprice_free=False
    )
    assert "maxprice=free" not in captured["url"]

    store_search.search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert "maxprice=free" in captured["url"]


def test_collect_category_paginates_until_target_reached(monkeypatch):
    # 2 страницы по 2 id, target_count=3 -> должно остановиться после 2-й
    # страницы (набрали 4 >= 3), не продолжая до конца total_count.
    pages = [_page_payload([1, 2], 100), _page_payload([3, 4], 100)]
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        resp = _FakeResp(pages[calls["n"]])
        calls["n"] += 1
        return resp

    monkeypatch.setattr(store_search.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(store_search.time, "sleep", lambda *_a: None)

    out = store_search.collect_category(
        category1=998,
        maxprice_free=True,
        target_count=3,
        page_size=2,
        max_pages=50,
    )
    assert out == [1, 2, 3, 4]
    assert calls["n"] == 2


def test_collect_category_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(
        store_search.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(_page_payload([], 0)),
    )
    out = store_search.collect_category(
        category1=998,
        maxprice_free=True,
        target_count=100,
        page_size=50,
        max_pages=50,
    )
    assert out == []


def test_collect_category_dedups_within_category(monkeypatch):
    pages = [_page_payload([1, 2], 100), _page_payload([2, 3], 100)]
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        resp = _FakeResp(pages[calls["n"]])
        calls["n"] += 1
        return resp

    monkeypatch.setattr(store_search.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(store_search.time, "sleep", lambda *_a: None)

    out = store_search.collect_category(
        category1=998,
        maxprice_free=True,
        target_count=10,
        page_size=2,
        max_pages=2,
    )
    assert out == [1, 2, 3]  # 2 не задублирован


def test_search_page_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error_429()
        return _FakeResp(_page_payload([730], 1))

    monkeypatch.setattr(store_search.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(store_search.time, "sleep", lambda *_a: None)

    appids, total = store_search.search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == [730]
    assert calls["n"] == 2


def test_search_page_network_error_returns_empty(monkeypatch):
    def fake_urlopen(req, timeout=15):
        raise OSError("connection reset")

    monkeypatch.setattr(store_search.urllib.request, "urlopen", fake_urlopen)
    appids, total = store_search.search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == []
    assert total == 0


def test_search_page_null_fields_return_empty_not_crash(monkeypatch):
    monkeypatch.setattr(
        store_search.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(
            {
                "success": 1,
                "results_html": None,
                "total_count": None,
                "start": 0,
            }
        ),
    )
    appids, total = store_search.search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == []
    assert total == 0
