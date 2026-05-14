"""Кэш результатов API-сканирования и прогресса обработки достижений."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .id_file import _append_id, load_ids_file

log = logging.getLogger("sam_automation")

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

GAMES_DIR = DATA_DIR / "games"
GAME_NAMES_FILE = GAMES_DIR / "names.json"

_IDS_DIR = GAMES_DIR / "ids"
_ACHIEVEMENTS_IDS_DIR = _IDS_DIR / "achievements"
CARDS_DIR = _IDS_DIR / "cards"

# Achievements
ALL_IDS_FILE = _IDS_DIR / "all.txt"
DONE_IDS_FILE = _ACHIEVEMENTS_IDS_DIR / "unlocked.txt"
ERROR_IDS_FILE = _ACHIEVEMENTS_IDS_DIR / "error.txt"
NO_ACHIEVEMENTS_FILE = _ACHIEVEMENTS_IDS_DIR / "without.txt"


def load_game_names() -> dict[int, str]:
    """Читает game_names.json → {appid: name}. Возвращает пустой dict если файл отсутствует."""
    try:
        raw: dict[str, str] = json.loads(GAME_NAMES_FILE.read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def save_game_names(names: dict[int, str]) -> None:
    """Сохраняет {appid: name} в game_names.json (merge с существующими)."""
    existing = load_game_names()
    existing.update(names)
    GAME_NAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    GAME_NAMES_FILE.write_text(
        json.dumps({str(k): v for k, v in sorted(existing.items())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_done_ids() -> set[int]:
    """Читает unlocked.txt → set[int]."""
    return load_ids_file(DONE_IDS_FILE)


def load_error_ids() -> set[int]:
    """Читает error.txt → set[int]."""
    return load_ids_file(ERROR_IDS_FILE)


def mark_done(game_id: int) -> None:
    """Дозаписывает game_id в unlocked.txt."""
    _append_id(DONE_IDS_FILE, game_id)


def mark_error_id(game_id: int) -> None:
    """Дозаписывает game_id в error.txt."""
    _append_id(ERROR_IDS_FILE, game_id)


def load_no_achievements_ids() -> set[int]:
    """Читает no_achievements.txt → set[int]."""
    return load_ids_file(NO_ACHIEVEMENTS_FILE)


def mark_no_achievements(game_id: int) -> None:
    """Дозаписывает game_id в no_achievements.txt."""
    _append_id(NO_ACHIEVEMENTS_FILE, game_id)


def clear_error_ids() -> None:
    """Удаляет error.txt (для retry-errors)."""
    if ERROR_IDS_FILE.exists():
        ERROR_IDS_FILE.unlink()
        log.debug("Удалён файл прогресса: %s", ERROR_IDS_FILE)


def clear_progress() -> None:
    """Удаляет unlocked.txt, error.txt и no_achievements.txt."""
    for path in (DONE_IDS_FILE, ERROR_IDS_FILE, NO_ACHIEVEMENTS_FILE):
        if path.exists():
            path.unlink()
            log.debug("Удалён файл прогресса: %s", path)
