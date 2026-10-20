"""Тесты обнаружения бесплатного контента по каталогу (app/free_games/discovery.py).

Каталог — IStoreService/GetAppList по типам (wishlist.discovery.discover_universe),
свойства — IStoreBrowseService/GetItems (wishlist.discovery.fetch_store_flags).
Здесь — только правила отбора: бесплатное, вышедшее, DLC — к своей игре.
"""

from __future__ import annotations

from app.free_games import discovery
from app.wishlist.discovery import StoreFlags


def _stub(monkeypatch, universe, flags, seen=None):  # type: ignore[no-untyped-def]
    seen = {} if seen is None else seen

    def fake_universe(api_key, *, types):
        seen["universe"] = (api_key, types)
        return universe

    def fake_flags(appids):
        seen["flags"] = list(appids)
        return flags

    monkeypatch.setattr(
        discovery.wl_discovery, "discover_universe", fake_universe
    )
    monkeypatch.setattr(discovery.wl_discovery, "fetch_store_flags", fake_flags)
    return seen


def test_keeps_free_released_and_dlc_of_owned_games(monkeypatch) -> None:
    flags = StoreFlags(
        free={2, 3, 4, 5, 6},
        coming_soon={3},
        parents={4: 100, 5: 200},
    )
    _stub(monkeypatch, [2, 3, 4, 5, 6, 7], flags)

    out = discovery.discover_candidates(
        api_key="k",
        types=frozenset({"games", "dlc"}),
        owned={100},
        exclude=set(),
    )

    # 3 не вышло, 5 — DLC к игре не из библиотеки, 7 платное
    assert out == [2, 4, 6]


def test_excluded_appids_are_not_checked_in_store(monkeypatch) -> None:
    seen = _stub(monkeypatch, [1, 2, 3], StoreFlags(free={1, 2, 3}))

    out = discovery.discover_candidates(
        api_key="k", types=frozenset({"games"}), owned=set(), exclude={1, 3}
    )

    assert out == [2]
    assert seen["flags"] == [2]


def test_types_and_key_go_to_catalog(monkeypatch) -> None:
    seen = _stub(monkeypatch, [], StoreFlags())

    discovery.discover_candidates(
        api_key="KEY", types=frozenset({"dlc"}), owned=set(), exclude=set()
    )

    assert seen["universe"] == ("KEY", frozenset({"dlc"}))
