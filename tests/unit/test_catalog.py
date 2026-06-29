"""Тесты advisory-каталога достижений (app/catalog.py).

Классификация Store — СОВЕТ, не пропуск. store_zero.txt отдельно от
without.txt (его пишет только SAM/farm); farm store_zero.txt не читает.
unknown не персистится → перезапрашивается.
"""

from __future__ import annotations

import app.catalog as catalog


def _patch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(catalog, "WITH_FILE", tmp_path / "with.txt")
    monkeypatch.setattr(catalog, "STORE_ZERO_FILE", tmp_path / "store_zero.txt")


def test_classify_positive_is_with() -> None:
    assert catalog.classify_achievements(5) == "with"


def test_classify_zero_is_store_zero() -> None:
    assert catalog.classify_achievements(0) == "store_zero"


def test_classify_none_is_unknown() -> None:
    assert catalog.classify_achievements(None) == "unknown"


def test_mark_and_load_with(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_with(10)
    catalog.mark_with(20)
    assert catalog.load_with_ids() == {10, 20}


def test_mark_and_load_store_zero(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_store_zero(7)
    assert catalog.load_store_zero_ids() == {7}


def test_clear_catalog_removes_both_files(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_with(1)
    catalog.mark_store_zero(2)
    catalog.clear_catalog()
    assert catalog.load_with_ids() == set()
    assert catalog.load_store_zero_ids() == set()


def test_remaining_excludes_classified_only() -> None:
    # unknown НЕ персистится → остаётся в remaining (перезапрос). Сортировка.
    remaining = catalog.remaining_to_classify(
        all_ids={1, 2, 3, 4}, with_ids={1}, zero_ids={2}
    )
    assert remaining == [3, 4]


def test_remaining_ignores_stale_ids_outside_library() -> None:
    # id в каталоге, которых нет в all.txt, не влияют на остаток.
    remaining = catalog.remaining_to_classify(
        all_ids={1, 2}, with_ids={1, 99}, zero_ids={42}
    )
    assert remaining == [2]
