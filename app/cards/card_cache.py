"""Кэш прогресса card farming (отдельно от кэша достижений)."""

from __future__ import annotations

from ..cache import CARDS_DIR
from ..id_file import _append_id

CARD_DONE_FILE = CARDS_DIR / "done.txt"


def mark_card_done(game_id: int) -> None:
    """Дозаписывает game_id в cards/done.txt."""
    _append_id(CARD_DONE_FILE, game_id)
