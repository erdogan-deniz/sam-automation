"""Кэш прогресса card farming (отдельно от кэша достижений)."""

from __future__ import annotations

import logging

from .cache import CARDS_DIR
from .id_file import _append_id, load_ids_file

log = logging.getLogger("sam_automation")

CARD_DONE_IDS_FILE = CARDS_DIR / "card_done_ids.txt"


def load_card_done_ids() -> set[int]:
    """Читает card_done_ids.txt → set[int] (игры без оставшихся card drops)."""
    return load_ids_file(CARD_DONE_IDS_FILE)


def mark_card_done(game_id: int) -> None:
    """Дозаписывает game_id в card_done_ids.txt."""
    _append_id(CARD_DONE_IDS_FILE, game_id)


def clear_card_progress() -> None:
    """Удаляет card_done_ids.txt (для нового запуска card farming)."""
    if CARD_DONE_IDS_FILE.exists():
        CARD_DONE_IDS_FILE.unlink()
        log.debug("Удалён файл прогресса: %s", CARD_DONE_IDS_FILE)
