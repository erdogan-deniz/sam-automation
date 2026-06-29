"""Тесты сводки по библиотеке достижений (app/stats.py)."""

from __future__ import annotations

from app.stats import LibraryStats, format_library_stats, library_stats


def test_empty_library_is_all_zeros() -> None:
    s = library_stats(set(), set(), set(), set())
    assert s == LibraryStats(
        total=0,
        without=0,
        with_ach=0,
        unlocked=0,
        error=0,
        pending=0,
        unlocked_pct=0.0,
    )


def test_counts_classify_library_into_categories() -> None:
    s = library_stats(
        all_ids={1, 2, 3, 4, 5},
        done_ids={1},
        error_ids={2},
        no_ach_ids={5},
    )
    assert s.total == 5
    assert s.without == 1
    assert s.with_ach == 4  # total - without
    assert s.unlocked == 1
    assert s.error == 1
    assert s.pending == 2  # with_ach - unlocked - error
    assert s.unlocked_pct == 25.0  # unlocked / with_ach


def test_ids_outside_library_are_ignored() -> None:
    # Устаревшие id в прогресс-файлах не считаются, если их нет в all.txt.
    s = library_stats(
        all_ids={1, 2},
        done_ids={1, 99},
        error_ids={42},
        no_ach_ids={2, 7},
    )
    assert s.total == 2
    assert s.unlocked == 1  # 99 не в библиотеке → проигнорирован
    assert s.error == 0  # 42 не в библиотеке
    assert s.without == 1  # 7 проигнорирован
    assert s.with_ach == 1  # total(2) - without(1)
    assert s.pending == 0  # with_ach(1) - unlocked(1) - error(0)


def test_pending_never_negative_on_overlapping_sets() -> None:
    # Защита от пересечений (id и в done, и в error одновременно).
    s = library_stats(
        all_ids={1, 2},
        done_ids={1, 2},
        error_ids={1, 2},
        no_ach_ids=set(),
    )
    assert s.pending == 0


def test_format_contains_labels_counts_and_progress() -> None:
    s = library_stats({1, 2, 3, 4}, {1}, {2}, {4})
    out = format_library_stats(s)
    assert "Всего" in out
    assert "4" in out  # total
    assert "33.3" in out  # прогресс 1/3 = 33.3%
