"""Тесты обнаружения бесплатных App ID через store search (app/free_games/discovery.py)."""

from __future__ import annotations

import email.message
import json
import urllib.error

from app.free_games import discovery


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
        discovery.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(_page_payload([730, 570], 19691)),
    )
    appids, total = discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == [730, 570]
    assert total == 19691


def test_search_page_maxprice_free_only_when_requested(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        return _FakeResp(_page_payload([], 0))

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)

    discovery._search_page(
        category1=10, start=0, count=100, maxprice_free=False
    )
    assert "maxprice=free" not in captured["url"]

    discovery._search_page(
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

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_a: None)

    out = discovery._collect_category(
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
        discovery.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(_page_payload([], 0)),
    )
    out = discovery._collect_category(
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

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_a: None)

    out = discovery._collect_category(
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

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_a: None)

    appids, total = discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == [730]
    assert calls["n"] == 2


def test_search_page_network_error_returns_empty(monkeypatch):
    def fake_urlopen(req, timeout=15):
        raise OSError("connection reset")

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    appids, total = discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == []
    assert total == 0


def test_discover_candidates_merges_and_dedups_across_sources(monkeypatch):
    call_order = []

    def fake_collect(*, category1, maxprice_free, **_kw):
        call_order.append(category1)
        return {
            discovery._CATEGORY_GAMES: [1, 2],
            discovery._CATEGORY_SOFTWARE: [2, 3],
            discovery._CATEGORY_DEMOS: [3, 4],
        }[category1]

    monkeypatch.setattr(discovery, "_collect_category", fake_collect)
    out = discovery.discover_candidates(include_demos=True)
    assert out == [1, 2, 3, 4]
    assert call_order == [998, 994, 10]


def test_discover_candidates_skips_demos_when_disabled(monkeypatch):
    def fake_collect(*, category1, **_kw):
        assert category1 != discovery._CATEGORY_DEMOS
        return [1]

    monkeypatch.setattr(discovery, "_collect_category", fake_collect)
    out = discovery.discover_candidates(include_demos=False)
    assert out == [1]
