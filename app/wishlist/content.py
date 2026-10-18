"""Типы контента вишлиста и их флаги (B-14).

Пять типов фильтрует сам GetAppList (`include_<тип>`). Демо в нём отдельного
фильтра нет (живая проба 19.10.2026: ни в одном из пяти списков нет ни одного
из 2443 известных демо), поэтому демо берутся из поиска витрины, как у
`add_demos.py`.
"""

from __future__ import annotations

from collections.abc import Iterable

APPLIST_TYPES = ("games", "dlc", "software", "videos", "hardware")
CONTENT_TYPES = (*APPLIST_TYPES, "demos")
ALL_TYPES = frozenset(CONTENT_TYPES)


def ordered(types: Iterable[str]) -> list[str]:
    """Типы в каноническом порядке CONTENT_TYPES (имя файла, лог)."""
    chosen = set(types)
    return [t for t in CONTENT_TYPES if t in chosen]


def label(types: Iterable[str]) -> str:
    """Подпись для лога: «все типы» или перечисление выбранных."""
    chosen = frozenset(types)
    return "все типы" if chosen == ALL_TYPES else ", ".join(ordered(chosen))
