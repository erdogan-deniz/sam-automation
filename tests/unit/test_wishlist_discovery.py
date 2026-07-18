"""Тесты app/wishlist/discovery.py: вселенная (GetAppList) + дедуп owned/wishlisted."""

from __future__ import annotations

from app.wishlist import discovery


def _apps_page(appids: list[int]) -> list[dict]:
    return [{"appid": a, "name": f"app{a}"} for a in appids]


# ── _fetch_universe_page ─────────────────────────────────────────────────────


def test_fetch_universe_page_parses_appids_have_more_and_cursor(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {
                "apps": _apps_page([10, 20, 30]),
                "have_more_results": True,
                "last_appid": 30,
            }
        },
    )
    appids, have_more, last_appid = discovery._fetch_universe_page(
        "key", last_appid=0
    )
    assert appids == [10, 20, 30]
    assert have_more is True
    assert last_appid == 30


def test_fetch_universe_page_requests_all_content_types(monkeypatch) -> None:
    captured = {}

    def fake_api_get(url: str) -> dict:
        captured["url"] = url
        return {
            "response": {
                "apps": [],
                "have_more_results": False,
                "last_appid": 0,
            }
        }

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)
    discovery._fetch_universe_page("mykey", last_appid=5)
    for flag in (
        "key=mykey",
        "include_games=1",
        "include_dlc=1",
        "include_software=1",
        "include_videos=1",
        "include_hardware=1",
        "last_appid=5",
    ):
        assert flag in captured["url"]


def test_fetch_universe_page_missing_response_returns_empty(
    monkeypatch,
) -> None:
    monkeypatch.setattr(discovery, "_api_get", lambda url: {})
    appids, have_more, last_appid = discovery._fetch_universe_page(
        "key", last_appid=0
    )
    assert appids == []
    assert have_more is False
    assert last_appid == 0


# ── discover_universe: пагинация до конца или max_pages ─────────────────────


def test_discover_universe_paginates_until_have_more_false(monkeypatch) -> None:
    pages = [
        {
            "response": {
                "apps": _apps_page([1, 2]),
                "have_more_results": True,
                "last_appid": 2,
            }
        },
        {
            "response": {
                "apps": _apps_page([3]),
                "have_more_results": False,
                "last_appid": 3,
            }
        },
    ]
    calls = {"n": 0}

    def fake_api_get(url: str) -> dict:
        page = pages[calls["n"]]
        calls["n"] += 1
        return page

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)
    out = discovery.discover_universe("key")
    assert out == [1, 2, 3]
    assert calls["n"] == 2


def test_discover_universe_stops_on_empty_page(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {"apps": [], "have_more_results": True, "last_appid": 0}
        },
    )
    out = discovery.discover_universe("key")
    assert out == []


def test_discover_universe_respects_max_pages_on_stuck_cursor(
    monkeypatch,
) -> None:
    # have_more всегда True, cursor не двигается (защита от зависания).
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {
                "apps": _apps_page([1]),
                "have_more_results": True,
                "last_appid": 0,
            }
        },
    )
    out = discovery.discover_universe("key", max_pages=3)
    assert out == [1, 1, 1]  # 3 страницы, затем max_pages останавливает
