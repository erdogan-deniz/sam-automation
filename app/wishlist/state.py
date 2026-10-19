"""Resume-состояние авто-добавления каталога Steam в вишлист.

Зеркало app/free_games/state.py, свой каталог data/games/ids/wishlist/ (не
пересекается с free/achievements/cards/playtime).

  candidates.txt — universe минус owned/wishlisted/added/refused (все типы)
  candidates_<типы>.txt — то же для выбранных флагами типов (B-14), напр.
                   candidates_games.txt; отдельный файл, чтобы --list одного
                   набора типов не показывал кандидатов другого
  added.txt      — успешно добавлено (x-eresult=1) — skip
  refused.txt    — терминально (owned/уже-в-вишлисте/invalid) — skip
  error.txt      — транзиентная сетевая ошибка — восстановим --retry-errors
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.cache import GAMES_DIR
from app.id_file import (
    _append_id,
    _atomic_write_text,
    _remove_id,
    load_ids_file,
    read_ids_ordered,
)
from app.wishlist.content import ALL_TYPES, ordered

_WISHLIST_DIR = GAMES_DIR / "ids" / "wishlist"

CANDIDATES_FILE = _WISHLIST_DIR / "candidates.txt"
ADDED_FILE = _WISHLIST_DIR / "added.txt"
REFUSED_FILE = _WISHLIST_DIR / "refused.txt"
ERROR_FILE = _WISHLIST_DIR / "error.txt"


def candidates_file(types: Iterable[str] = ALL_TYPES) -> Path:
    """candidates.txt для всех типов, иначе candidates_<типы>.txt."""
    chosen = frozenset(types)
    if chosen == ALL_TYPES:
        return CANDIDATES_FILE
    return CANDIDATES_FILE.with_name(
        f"candidates_{'_'.join(ordered(chosen))}.txt"
    )


def load_candidates(types: Iterable[str] = ALL_TYPES) -> list[int]:
    """candidates с сохранением порядка обнаружения (дедуп первых вхождений)."""
    return read_ids_ordered(candidates_file(types))


def save_candidates(
    appids: list[int], types: Iterable[str] = ALL_TYPES
) -> None:
    """Атомарно перезаписывает candidates (числовая сортировка, дедуп)."""
    _atomic_write_text(
        candidates_file(types),
        "\n".join(str(i) for i in sorted(set(appids))) + "\n",
    )


def load_added_ids() -> set[int]:
    return load_ids_file(ADDED_FILE)


def load_refused_ids() -> set[int]:
    return load_ids_file(REFUSED_FILE)


def load_error_ids() -> set[int]:
    return load_ids_file(ERROR_FILE)


def mark_added(appid: int) -> None:
    _append_id(ADDED_FILE, appid)


def unmark_added(appid: int) -> None:
    """Убирает appid из added.txt: удалён из вишлиста чисткой (B-18) —
    вышедшая игра снова попадёт в кандидатов."""
    _remove_id(ADDED_FILE, appid)


def mark_refused(appid: int) -> None:
    _append_id(REFUSED_FILE, appid)


def mark_error(appid: int) -> None:
    _append_id(ERROR_FILE, appid)


def clear_error_ids() -> None:
    """Удаляет error.txt (для --retry-errors — только транзиент, НЕ refused)."""
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()


def clear_state() -> None:
    """Удаляет ВСЁ resume-состояние (--reset), кандидатов всех наборов типов."""
    paths = [
        CANDIDATES_FILE,
        *CANDIDATES_FILE.parent.glob("candidates_*.txt"),
        ADDED_FILE,
        REFUSED_FILE,
        ERROR_FILE,
    ]
    for path in paths:
        if path.exists():
            path.unlink()
