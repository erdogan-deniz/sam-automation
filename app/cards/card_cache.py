"""Кэш прогресса card farming (отдельно от кэша достижений)."""

from __future__ import annotations

import logging

from ..cache import CARDS_DIR
from ..id_file import _append_id

log = logging.getLogger("sam_automation")

CARD_DONE_FILE = CARDS_DIR / "done.txt"


def mark_card_done(game_id: int) -> None:
    """Дозаписывает game_id в cards/done.txt."""
    _append_id(CARD_DONE_FILE, game_id)


def clear_card_progress() -> None:
    """Удаляет cards/done.txt (для нового запуска card farming)."""
    if CARD_DONE_FILE.exists():
        CARD_DONE_FILE.unlink()
        log.debug("Удалён файл прогресса: %s", CARD_DONE_FILE)
