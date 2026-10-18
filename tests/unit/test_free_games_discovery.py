"""Тесты обнаружения бесплатных App ID через store search (app/free_games/discovery.py).

Тесты уровня пагинации (search_page/collect_category) — в
test_store_search.py (2026-09-12, вынесено в app.steam.store_search).
Здесь — только discover_candidates: слияние источников GAMES+SOFTWARE.
"""

from __future__ import annotations

from app.free_games import discovery


def test_discover_candidates_merges_and_dedups_across_sources(monkeypatch):
    call_order = []

    def fake_collect(*, category1, maxprice_free, **_kw):
        call_order.append(category1)
        return {
            discovery._CATEGORY_GAMES: [1, 2],
            discovery._CATEGORY_SOFTWARE: [2, 3],
        }[category1]

    monkeypatch.setattr(
        discovery.store_search, "collect_category", fake_collect
    )
    out = discovery.discover_candidates()
    assert out == [1, 2, 3]
    assert call_order == [998, 994]
