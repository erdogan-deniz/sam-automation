"""Состояние чистки вишлиста (B-17/B-18): свой каталог data/games/ids/wishlist_clean/.

candidates.txt — что удалить: бесплатное и/или не вышедшее из вишлиста,
                 перезаписывается каждым discover
removed.txt    — удалено (или Steam ответил, что позиции уже нет)
"""

from __future__ import annotations

from app.cache import GAMES_DIR
from app.id_file import (
    _append_id,
    _atomic_write_text,
    load_ids_file,
    read_ids_ordered,
)

_CLEAN_DIR = GAMES_DIR / "ids" / "wishlist_clean"

CANDIDATES_FILE = _CLEAN_DIR / "candidates.txt"
REMOVED_FILE = _CLEAN_DIR / "removed.txt"


def load_candidates() -> list[int]:
    return read_ids_ordered(CANDIDATES_FILE)


def save_candidates(appids: list[int]) -> None:
    """Атомарно перезаписывает candidates.txt (числовая сортировка, дедуп)."""
    _atomic_write_text(
        CANDIDATES_FILE, "\n".join(str(i) for i in sorted(set(appids))) + "\n"
    )


def load_removed_ids() -> set[int]:
    return load_ids_file(REMOVED_FILE)


def mark_removed(appid: int) -> None:
    _append_id(REMOVED_FILE, appid)
