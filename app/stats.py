"""Сводка по библиотеке достижений: классификация all.txt по прогресс-файлам."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .logging_setup import SEPARATOR


@dataclass(frozen=True)
class LibraryStats:
    """Срез состояния библиотеки достижений."""

    total: int  # всего игр в библиотеке (all.txt)
    without: int  # подтверждённо без достижений (without.txt)
    with_ach: int  # с достижениями = total - without
    unlocked: int  # достижения выбиты (unlocked.txt)
    error: int  # обработка завершилась ошибкой (error.txt)
    pending: int  # с достижениями, ещё не обработаны
    unlocked_pct: float  # unlocked / with_ach * 100


def library_stats(
    all_ids: Iterable[int],
    done_ids: Iterable[int],
    error_ids: Iterable[int],
    no_ach_ids: Iterable[int],
) -> LibraryStats:
    """Классифицирует библиотеку (all_ids) по прогресс-множествам.

    Все прогресс-множества пересекаются с all_ids: устаревшие id, которых уже
    нет в библиотеке, игнорируются. pending не уходит в минус при пересечениях.
    """
    library = set(all_ids)
    total = len(library)
    without = len(set(no_ach_ids) & library)
    with_ach = total - without
    unlocked = len(set(done_ids) & library)
    error = len(set(error_ids) & library)
    pending = max(with_ach - unlocked - error, 0)
    unlocked_pct = round(unlocked / with_ach * 100, 1) if with_ach else 0.0
    return LibraryStats(
        total=total,
        without=without,
        with_ach=with_ach,
        unlocked=unlocked,
        error=error,
        pending=pending,
        unlocked_pct=unlocked_pct,
    )


def format_library_stats(stats: LibraryStats) -> str:
    """Человекочитаемая сводка для печати в консоль/лог."""
    lines = [
        SEPARATOR,
        "СВОДКА ПО БИБЛИОТЕКЕ ДОСТИЖЕНИЙ",
        SEPARATOR,
        f"Всего игр:           {stats.total}",
        f"С достижениями:      {stats.with_ach}",
        f"Без достижений:      {stats.without}",
        f"  ├─ выбито:         {stats.unlocked}",
        f"  ├─ ошибки:         {stats.error}",
        f"  └─ осталось:       {stats.pending}",
        f"Прогресс: {stats.unlocked_pct}% ({stats.unlocked}/{stats.with_ach})",
        SEPARATOR,
    ]
    return "\n".join(lines)
