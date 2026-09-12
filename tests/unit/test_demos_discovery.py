"""Тесты обнаружения demo App ID через store search (app/demos/discovery.py).

Пагинация переиспользуется из app.steam.store_search (уже покрыта
test_store_search.py) — здесь только discover_candidates: единственный
источник, категория Demos (category1=10, без maxprice — демо всегда бесплатны).
"""

from __future__ import annotations

from app.demos import discovery


def test_discover_candidates_uses_demos_category_without_maxprice(
    monkeypatch,
):
    captured = {}

    def fake_collect(*, category1, maxprice_free, **_kw):
        captured["category1"] = category1
        captured["maxprice_free"] = maxprice_free
        return [1, 2]

    monkeypatch.setattr(
        discovery.store_search, "collect_category", fake_collect
    )
    out = discovery.discover_candidates()

    assert out == [1, 2]
    assert captured["category1"] == discovery._CATEGORY_DEMOS
    assert captured["maxprice_free"] is False


def test_discover_candidates_dedups(monkeypatch):
    monkeypatch.setattr(
        discovery.store_search,
        "collect_category",
        lambda **_kw: [1, 2, 2, 3],
    )
    out = discovery.discover_candidates()
    assert out == [1, 2, 3]
