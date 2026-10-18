"""Типы контента вишлиста — фильтры GetAppList `include_<тип>` (B-14).

DLC и демо в вишлист не идут (решение владельца 19.10.2026): демо добавляет
в библиотеку `add_demos.py`, бесплатные DLC — туда же (R-6), платные DLC
владелец из вишлиста убирает (B-13).
"""

from __future__ import annotations

from collections.abc import Iterable

# Все фильтры GetAppList — каждый передаётся явно: include_games у него по
# умолчанию включён, а со всеми нулями он отдаёт весь каталог без фильтра.
APPLIST_FILTERS = ("games", "dlc", "software", "videos", "hardware")
CONTENT_TYPES = ("games", "software", "videos", "hardware")
ALL_TYPES = frozenset(CONTENT_TYPES)


def ordered(types: Iterable[str]) -> list[str]:
    """Типы в каноническом порядке CONTENT_TYPES (имя файла, лог)."""
    chosen = set(types)
    return [t for t in CONTENT_TYPES if t in chosen]


def label(types: Iterable[str]) -> str:
    """Подпись для лога: «все типы» или перечисление выбранных."""
    chosen = frozenset(types)
    return "все типы" if chosen == ALL_TYPES else ", ".join(ordered(chosen))
