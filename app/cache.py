"""Кэш результатов API-сканирования и прогресса обработки достижений."""

from __future__ import annotations

import logging
from pathlib import Path

from .id_file import _append_id, load_ids_file  # noqa: F401 — re-export

log = logging.getLogger("sam_automation")

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

_ACHIEVEMENTS_DIR = DATA_DIR / "achievements"
CARDS_DIR = DATA_DIR / "cards"

# Текстовые файлы состояния
ALL_IDS_FILE = _ACHIEVEMENTS_DIR / "ids.txt"
DONE_IDS_FILE = _ACHIEVEMENTS_DIR / "done_ids.txt"
ERROR_IDS_FILE = _ACHIEVEMENTS_DIR / "error_ids.txt"
NO_ACHIEVEMENTS_FILE = _ACHIEVEMENTS_DIR / "no_achievements_ids.txt"


def load_done_ids() -> set[int]:
    """Читает done_ids.txt → set[int]."""
    return load_ids_file(DONE_IDS_FILE)


def load_error_ids() -> set[int]:
    """Читает error_ids.txt → set[int]."""
    return load_ids_file(ERROR_IDS_FILE)


def mark_done(game_id: int) -> None:
    """Дозаписывает game_id в done_ids.txt."""
    _append_id(DONE_IDS_FILE, game_id)


def mark_error_id(game_id: int) -> None:
    """Дозаписывает game_id в error_ids.txt."""
    _append_id(ERROR_IDS_FILE, game_id)


def load_no_achievements_ids() -> set[int]:
    """Читает no_achievements_ids.txt → set[int]."""
    return load_ids_file(NO_ACHIEVEMENTS_FILE)


def mark_no_achievements(game_id: int) -> None:
    """Дозаписывает game_id в no_achievements_ids.txt."""
    _append_id(NO_ACHIEVEMENTS_FILE, game_id)


def clear_progress() -> None:
    """Удаляет done_ids.txt, error_ids.txt и no_achievements_ids.txt."""
    for path in (DONE_IDS_FILE, ERROR_IDS_FILE, NO_ACHIEVEMENTS_FILE):
        if path.exists():
            path.unlink()
            log.debug("Удалён файл прогресса: %s", path)
