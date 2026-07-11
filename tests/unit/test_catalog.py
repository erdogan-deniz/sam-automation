"""Тесты advisory-каталога достижений (app/catalog.py).

Классификация Store — СОВЕТ, не пропуск. with/store_zero/store_empty отдельно
от without.txt (его пишет только SAM/farm); farm их НЕ читает. unknown
(транзиентный сбой) не персистится → перезапрашивается.
"""

from __future__ import annotations

import app.catalog as catalog
from app.steam.store_api import AchievementInfo


def _patch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(catalog, "WITH_FILE", tmp_path / "with.txt")
    monkeypatch.setattr(catalog, "STORE_ZERO_FILE", tmp_path / "store_zero.txt")
    monkeypatch.setattr(
        catalog, "STORE_EMPTY_FILE", tmp_path / "store_empty.txt"
    )


def test_classify_positive_is_with() -> None:
    assert catalog.classify_achievements(AchievementInfo(5, True)) == "with"


def test_classify_zero_is_store_zero() -> None:
    info = AchievementInfo(0, True)
    assert catalog.classify_achievements(info) == "store_zero"


def test_classify_responded_empty_is_store_empty() -> None:
    # Store ответил, но достижений нет (data:[]) → стабильный store_empty.
    info = AchievementInfo(None, True)
    assert catalog.classify_achievements(info) == "store_empty"


def test_classify_not_responded_is_unknown() -> None:
    # Транзиентный сбой сети → unknown (перезапрос), НЕ персистится.
    info = AchievementInfo(None, False)
    assert catalog.classify_achievements(info) == "unknown"


def test_mark_and_load_with(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_with(10)
    catalog.mark_with(20)
    assert catalog.load_with_ids() == {10, 20}


def test_mark_and_load_store_zero(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_store_zero(7)
    assert catalog.load_store_zero_ids() == {7}


def test_mark_and_load_store_empty(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_store_empty(9)
    assert catalog.load_store_empty_ids() == {9}


def test_unmark_store_advisory_clears_both_advisory_files(
    monkeypatch, tmp_path
) -> None:
    # SAM вынес вердикт → снимаем Store-советы store_zero И store_empty.
    _patch(monkeypatch, tmp_path)
    catalog.mark_store_zero(7)
    catalog.mark_store_empty(9)
    catalog.unmark_store_advisory(7)
    catalog.unmark_store_advisory(9)
    assert catalog.load_store_zero_ids() == set()
    assert catalog.load_store_empty_ids() == set()


def test_unmark_store_advisory_leaves_with_untouched(
    monkeypatch, tmp_path
) -> None:
    # with.txt — положительный сигнал, unmark_store_advisory его не трогает.
    _patch(monkeypatch, tmp_path)
    catalog.mark_with(5)
    catalog.unmark_store_advisory(5)
    assert catalog.load_with_ids() == {5}


def test_unmark_store_advisory_absent_is_noop(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.unmark_store_advisory(123)  # файлов нет — не должно падать


def test_clear_catalog_removes_all_three_files(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    catalog.mark_with(1)
    catalog.mark_store_zero(2)
    catalog.mark_store_empty(3)
    catalog.clear_catalog()
    assert catalog.load_with_ids() == set()
    assert catalog.load_store_zero_ids() == set()
    assert catalog.load_store_empty_ids() == set()


def test_remaining_excludes_all_classified() -> None:
    # unknown НЕ персистится → остаётся в remaining. with/zero/empty исключены.
    remaining = catalog.remaining_to_classify(
        all_ids={1, 2, 3, 4, 5},
        with_ids={1},
        zero_ids={2},
        empty_ids={3},
    )
    assert remaining == [4, 5]


def test_remaining_ignores_stale_ids_outside_library() -> None:
    remaining = catalog.remaining_to_classify(
        all_ids={1, 2},
        with_ids={1, 99},
        zero_ids={42},
        empty_ids={7},
    )
    assert remaining == [2]


# ── prioritize_by_with: with.txt-игры вперёд (advisory, порядок) ──


def test_prioritize_moves_with_games_to_front_stable() -> None:
    # with={2,4} → они в начале, относительный порядок обеих групп сохранён.
    assert catalog.prioritize_by_with([1, 2, 3, 4, 5], {2, 4}) == [
        2,
        4,
        1,
        3,
        5,
    ]


def test_prioritize_empty_with_keeps_order() -> None:
    # Пустой каталог (не запускали categorize) → список без изменений.
    assert catalog.prioritize_by_with([1, 2, 3], set()) == [1, 2, 3]


def test_prioritize_ignores_with_ids_not_in_list() -> None:
    # id из with.txt, которых нет в списке farm, ничего не вставляют.
    assert catalog.prioritize_by_with([1, 2], {99}) == [1, 2]


def test_prioritize_preserves_all_games_no_dupes() -> None:
    # advisory: ни одна игра не теряется и не дублируется — только переупорядочена.
    out = catalog.prioritize_by_with([3, 1, 2], {1})
    assert sorted(out) == [1, 2, 3]
    assert len(out) == 3
