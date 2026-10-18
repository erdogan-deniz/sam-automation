"""Типы контента вишлиста — фильтры GetAppList `include_<тип>` (B-14).

Демо сюда не входят: у GetAppList их фильтра нет, а в библиотеку их и так
добавляет `add_demos.py` (решение владельца 19.10.2026).
"""

from __future__ import annotations

from collections.abc import Iterable

CONTENT_TYPES = ("games", "dlc", "software", "videos", "hardware")
ALL_TYPES = frozenset(CONTENT_TYPES)


def ordered(types: Iterable[str]) -> list[str]:
    """Типы в каноническом порядке CONTENT_TYPES (имя файла, лог)."""
    chosen = set(types)
    return [t for t in CONTENT_TYPES if t in chosen]


def label(types: Iterable[str]) -> str:
    """Подпись для лога: «все типы» или перечисление выбранных."""
    chosen = frozenset(types)
    return "все типы" if chosen == ALL_TYPES else ", ".join(ordered(chosen))
