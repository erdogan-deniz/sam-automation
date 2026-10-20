"""Тесты app/wishlist/discovery.py: вселенная (GetAppList) + дедуп owned/wishlisted."""

from __future__ import annotations

import pytest

from app.wishlist import discovery

_REAL_FETCH_STORE_FLAGS = discovery.fetch_store_flags


@pytest.fixture(autouse=True)
def _no_free_check(monkeypatch):  # type: ignore[no-untyped-def]
    # Проверка магазина ходит в Steam — в тестах discover_candidates по
    # умолчанию нет ни бесплатного, ни не вышедшего; свои тесты подменяют сами.
    monkeypatch.setattr(
        discovery, "fetch_store_flags", lambda _ids: discovery.StoreFlags()
    )


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


def _capture_url(monkeypatch) -> dict:  # type: ignore[no-untyped-def]
    captured: dict = {}

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
    return captured


def test_fetch_universe_page_default_requests_all_types(
    monkeypatch,
) -> None:
    captured = _capture_url(monkeypatch)
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


def test_fetch_universe_page_software_requests_only_software(
    monkeypatch,
) -> None:
    # B-14. include_games у GetAppList по умолчанию true — выключать явно.
    captured = _capture_url(monkeypatch)
    discovery._fetch_universe_page(
        "mykey", last_appid=5, types=frozenset({"software"})
    )
    for flag in (
        "include_games=0",
        "include_dlc=0",
        "include_software=1",
        "include_videos=0",
        "include_hardware=0",
    ):
        assert flag in captured["url"]


def test_discover_universe_passes_types_to_every_page(monkeypatch) -> None:
    seen: list[frozenset[str]] = []

    def fake_page(api_key, *, last_appid, types, **_kw):
        seen.append(types)
        return [1], len(seen) < 2, len(seen)

    monkeypatch.setattr(discovery, "_fetch_universe_page", fake_page)
    games = frozenset({"games"})
    assert discovery.discover_universe("key", types=games) == [1, 1]
    assert seen == [games, games]


def test_discover_universe_empty_types_skips_applist(monkeypatch) -> None:
    # Со всеми include_*=0 GetAppList отдаёт весь каталог без фильтра.
    def _boom(*_a, **_k):
        raise AssertionError("GetAppList не должен вызываться")

    monkeypatch.setattr(discovery, "_fetch_universe_page", _boom)
    assert discovery.discover_universe("k", types=frozenset()) == []


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


# ── fetch_store_flags: GetItems пачками → бесплатное и не вышедшее ───────


def test_fetch_store_flags_batches_and_collects(monkeypatch) -> None:
    urls: list[str] = []

    def fake_api_get(url: str) -> dict:
        urls.append(url)
        return {
            "response": {
                "store_items": [
                    {"appid": 2, "is_free": True},
                    {"appid": 3},
                    {"appid": 450, "is_free": True},
                    {"appid": 7, "is_free": False},
                    {"appid": 8, "is_coming_soon": True},
                    {"appid": 9, "release": {"is_coming_soon": True}},
                ]
            }
        }

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)

    out = _REAL_FETCH_STORE_FLAGS(list(range(1, 451)))

    assert out.free == {2, 450}
    assert out.coming_soon == {8, 9}
    assert len(urls) == 3  # 450 appid пачками по 200
    assert all("IStoreBrowseService/GetItems/v1" in u for u in urls)


def test_fetch_store_flags_collects_dlc_parents(monkeypatch) -> None:
    # Живая проба 21.10.2026: у DLC GetItems отдаёт related_items.parent_appid.
    def fake_api_get(url: str) -> dict:
        return {
            "response": {
                "store_items": [
                    {
                        "appid": 348690,
                        "related_items": {"parent_appid": 333250},
                    },
                    {"appid": 333250},
                    {"appid": 5, "related_items": {}},
                ]
            }
        }

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)

    out = _REAL_FETCH_STORE_FLAGS([348690, 333250, 5])

    assert out.parents == {348690: 333250}


def test_fetch_store_flags_empty_input_makes_no_requests(monkeypatch) -> None:
    def _boom(url):
        raise AssertionError("без кандидатов запросов быть не должно")

    monkeypatch.setattr(discovery, "_api_get", _boom)
    assert _REAL_FETCH_STORE_FLAGS([]) == discovery.StoreFlags()


def test_fetch_store_flags_sends_country_code(monkeypatch) -> None:
    # Без country_code Steam отдаёт пустой response (живая проба 19.10.2026).
    urls: list[str] = []

    def fake_api_get(url: str) -> dict:
        urls.append(url)
        return {"response": {"store_items": []}}

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)
    _REAL_FETCH_STORE_FLAGS([1])
    assert "country_code" in urls[0]


def test_fetch_store_flags_response_without_items_raises(monkeypatch) -> None:
    # Пустой response — не «ничего бесплатного», а непроверенная пачка.
    monkeypatch.setattr(discovery, "_api_get", lambda url: {"response": {}})
    with pytest.raises(RuntimeError, match="store_items"):
        _REAL_FETCH_STORE_FLAGS([1, 2])


def test_fetch_store_flags_cools_down_after_rate_limit(monkeypatch) -> None:
    # Живой прогон 19.10.2026: на 760 пачках Steam то и дело отвечал 429;
    # исчерпанный ретрай _api_get не должен ронять весь discover.
    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky(url: str) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            raise discovery._RateLimitError("429", None)
        return {"response": {"store_items": [{"appid": 1, "is_free": True}]}}

    monkeypatch.setattr(discovery, "_api_get", flaky)
    monkeypatch.setattr(discovery.time, "sleep", sleeps.append)

    assert _REAL_FETCH_STORE_FLAGS([1]).free == {1}
    assert sleeps == [discovery._ITEMS_COOLDOWN]


def test_fetch_store_flags_gives_up_after_cooldowns(monkeypatch) -> None:
    def always_429(url: str) -> dict:
        raise discovery._RateLimitError("429", None)

    monkeypatch.setattr(discovery, "_api_get", always_429)
    monkeypatch.setattr(discovery.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError):
        _REAL_FETCH_STORE_FLAGS([1])


def test_fetch_store_flags_failure_propagates(monkeypatch) -> None:
    def _boom(url):
        raise RuntimeError("Steam API вернул 500")

    monkeypatch.setattr(discovery, "_api_get", _boom)
    with pytest.raises(RuntimeError, match="500"):
        _REAL_FETCH_STORE_FLAGS([1, 2])


# ── fetch_wishlist_ids: keyless GetWishlist, весь список одним ответом ──────


def test_fetch_wishlist_ids_parses_items(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {
                "items": [
                    {"appid": 1200, "priority": 0, "date_added": 111},
                    {"appid": 730, "priority": 1, "date_added": 222},
                ]
            }
        },
    )
    assert discovery.fetch_wishlist_ids("76561198190468628") == {1200, 730}


def test_fetch_wishlist_ids_empty_response(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "_api_get", lambda url: {"response": {}})
    assert discovery.fetch_wishlist_ids("76561198190468628") == set()


# ── discover_candidates: universe − owned − wishlisted, устойчиво к сбоям ──


def test_discover_candidates_subtracts_owned_and_wishlisted(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        discovery, "discover_universe", lambda _key, **_kw: [1, 2, 3, 4, 5]
    )
    monkeypatch.setattr(
        discovery,
        "fetch_owned_games",
        lambda _key, _sid: [{"appid": 2, "name": "owned"}],
    )
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: {3})

    out = discovery.discover_candidates(
        api_key="key", steam_id="76561198190468628"
    )
    assert out == [1, 4, 5]


def test_discover_candidates_passes_types_to_universe(monkeypatch) -> None:
    captured = {}

    def fake_universe(_key, *, types, **_kw):
        captured["types"] = types
        return []

    monkeypatch.setattr(discovery, "discover_universe", fake_universe)
    monkeypatch.setattr(discovery, "fetch_owned_games", lambda _k, _s: [])
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: set())

    discovery.discover_candidates(
        api_key="key",
        steam_id="76561198190468628",
        types=frozenset({"software"}),
    )
    assert captured["types"] == frozenset({"software"})


def test_discover_candidates_drops_free_content(monkeypatch) -> None:
    # Решение владельца 19.10.2026: в вишлист — только платное, бесплатное
    # забирает add_free_content.py. Проверяем бесплатность только у оставшихся.
    monkeypatch.setattr(
        discovery, "discover_universe", lambda _key, **_kw: [1, 2, 3, 4, 5]
    )
    monkeypatch.setattr(
        discovery, "fetch_owned_games", lambda _k, _s: [{"appid": 2}]
    )
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: {3})
    checked: list[list[int]] = []

    def fake_flags(ids):
        checked.append(list(ids))
        return discovery.StoreFlags(free={4})

    monkeypatch.setattr(discovery, "fetch_store_flags", fake_flags)

    out = discovery.discover_candidates(api_key="k", steam_id="s")

    assert out == [1, 5]
    assert checked == [[1, 4, 5]]


def test_discover_candidates_drops_coming_soon(monkeypatch) -> None:
    # Решение владельца 19.10.2026: не вышедшее в вишлист не добавляем.
    monkeypatch.setattr(
        discovery, "discover_universe", lambda _k, **_kw: [1, 2, 3]
    )
    monkeypatch.setattr(discovery, "fetch_owned_games", lambda _k, _s: [])
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: set())
    monkeypatch.setattr(
        discovery,
        "fetch_store_flags",
        lambda _ids: discovery.StoreFlags(free={1}, coming_soon={3}),
    )

    assert discovery.discover_candidates(api_key="k", steam_id="s") == [2]


def test_discover_candidates_free_check_failure_propagates(monkeypatch) -> None:
    # Без проверки бесплатности кандидаты не сохраняются: иначе бесплатное
    # хлынуло бы в вишлист.
    monkeypatch.setattr(discovery, "discover_universe", lambda _k, **_kw: [1])
    monkeypatch.setattr(discovery, "fetch_owned_games", lambda _k, _s: [])
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: set())

    def _boom(_ids):
        raise RuntimeError("GetItems упал")

    monkeypatch.setattr(discovery, "fetch_store_flags", _boom)
    with pytest.raises(RuntimeError, match="GetItems"):
        discovery.discover_candidates(api_key="k", steam_id="s")


def test_discover_candidates_universe_failure_propagates(
    monkeypatch,
) -> None:
    # Живая находка 2026-07-19: транзиентный SSL-обрыв GetAppList не должен
    # тихо глотаться в "0 кандидатов" — orchestrate.discover() перезаписал бы
    # им честный (но реальный) candidates.txt пустым списком. Universe-сбой
    # пробрасывается, чтобы вызывающий НЕ вызвал save_candidates().
    def _boom(_key, **_kw):
        raise RuntimeError("Steam API вернул 500")

    monkeypatch.setattr(discovery, "discover_universe", _boom)
    with pytest.raises(RuntimeError, match="Steam API вернул 500"):
        discovery.discover_candidates(
            api_key="key", steam_id="76561198190468628"
        )


def test_discover_candidates_owned_failure_still_returns_candidates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        discovery, "discover_universe", lambda _key, **_kw: [1, 2]
    )

    def _boom(_key, _sid):
        raise RuntimeError("GetOwnedGames упал")

    monkeypatch.setattr(discovery, "fetch_owned_games", _boom)
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: set())

    out = discovery.discover_candidates(
        api_key="key", steam_id="76561198190468628"
    )
    assert out == [1, 2]  # owned не вычтен, но прогон не падает


def test_discover_candidates_wishlist_failure_still_returns_candidates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        discovery, "discover_universe", lambda _key, **_kw: [1, 2]
    )
    monkeypatch.setattr(discovery, "fetch_owned_games", lambda _key, _sid: [])

    def _boom(_sid):
        raise RuntimeError("GetWishlist упал")

    monkeypatch.setattr(discovery, "fetch_wishlist_ids", _boom)

    out = discovery.discover_candidates(
        api_key="key", steam_id="76561198190468628"
    )
    assert out == [1, 2]  # wishlisted не вычтен, но прогон не падает
