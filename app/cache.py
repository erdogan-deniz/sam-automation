"""Кэш результатов API-сканирования и прогресса обработки достижений."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .id_file import (
    _append_id,
    _atomic_write_text,
    _remove_id,
    load_ids_file,
)

log = logging.getLogger("sam_automation")

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

GAMES_DIR = DATA_DIR / "games"
GAME_NAMES_FILE = GAMES_DIR / "names.json"

_IDS_DIR = GAMES_DIR / "ids"
_ACHIEVEMENTS_IDS_DIR = _IDS_DIR / "achievements"
CARDS_DIR = _IDS_DIR / "cards"
_PLAYTIME_IDS_DIR = _IDS_DIR / "playtime"

# Playtime: игры, которые не подключаются к Steam через SAM (playtest/демо и пр.)
PLAYTIME_SKIP_FILE = _PLAYTIME_IDS_DIR / "skip.txt"
# Playtime: игры, которым уже набили время (resume — не идлить повторно)
PLAYTIME_DONE_FILE = _PLAYTIME_IDS_DIR / "done.txt"

# Achievements
ALL_IDS_FILE = _IDS_DIR / "all.txt"
DONE_IDS_FILE = _ACHIEVEMENTS_IDS_DIR / "unlocked.txt"
ERROR_IDS_FILE = _ACHIEVEMENTS_IDS_DIR / "error.txt"
NO_ACHIEVEMENTS_FILE = _ACHIEVEMENTS_IDS_DIR / "without.txt"


def load_game_names() -> dict[int, str]:
    """Читает names.json → {appid: name}. Возвращает пустой dict если файл отсутствует."""
    try:
        raw: dict[str, str] = json.loads(
            GAME_NAMES_FILE.read_text(encoding="utf-8")
        )
        return {int(k): v for k, v in raw.items()}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def save_game_names(names: dict[int, str]) -> None:
    """Сохраняет {appid: name} в names.json (merge с существующими)."""
    existing = load_game_names()
    existing.update(names)
    _atomic_write_text(
        GAME_NAMES_FILE,
        json.dumps(
            {str(k): v for k, v in sorted(existing.items())},
            ensure_ascii=False,
            indent=2,
        ),
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
    """Читает without.txt → set[int]."""
    return load_ids_file(NO_ACHIEVEMENTS_FILE)


def mark_no_achievements(game_id: int) -> None:
    """Дозаписывает game_id в without.txt."""
    _append_id(NO_ACHIEVEMENTS_FILE, game_id)


def unmark_no_achievements(game_id: int) -> None:
    """Удаляет game_id из without.txt (игра оказалась с достижениями).

    No-op, если игры там нет. Нужен для --retry-without: если SAM при
    перепроверке разблокировал достижения, устаревшая пометка «без
    достижений» должна уйти — иначе файл соврёт при следующем прогоне.
    """
    _remove_id(NO_ACHIEVEMENTS_FILE, game_id)


def load_playtime_skip_ids() -> set[int]:
    """Читает playtime/skip.txt → set[int] (игры, не подключающиеся к Steam)."""
    return load_ids_file(PLAYTIME_SKIP_FILE)


def mark_playtime_skip(appid: int) -> None:
    """Дозаписывает appid в playtime/skip.txt."""
    _append_id(PLAYTIME_SKIP_FILE, appid)


def load_playtime_done_ids() -> set[int]:
    """Читает playtime/done.txt → set[int] (игры с уже набитым временем)."""
    return load_ids_file(PLAYTIME_DONE_FILE)


def mark_playtime_done(appid: int) -> None:
    """Дозаписывает appid в playtime/done.txt."""
    _append_id(PLAYTIME_DONE_FILE, appid)


def clear_playtime_progress() -> None:
    """Удаляет playtime/done.txt (для повторной набивки всех игр)."""
    if PLAYTIME_DONE_FILE.exists():
        PLAYTIME_DONE_FILE.unlink()
        log.debug("Удалён файл прогресса: %s", PLAYTIME_DONE_FILE)


def clear_playtime_skip() -> None:
    """Удаляет playtime/skip.txt (ретрай игр, ранее не подключившихся к Steam)."""
    if PLAYTIME_SKIP_FILE.exists():
        PLAYTIME_SKIP_FILE.unlink()
        log.debug("Удалён файл прогресса: %s", PLAYTIME_SKIP_FILE)


def clear_error_ids() -> None:
    """Удаляет error.txt (для retry-errors)."""
    if ERROR_IDS_FILE.exists():
        ERROR_IDS_FILE.unlink()
        log.debug("Удалён файл прогресса: %s", ERROR_IDS_FILE)


def clear_progress() -> None:
    """Удаляет unlocked.txt, error.txt и without.txt."""
    for path in (DONE_IDS_FILE, ERROR_IDS_FILE, NO_ACHIEVEMENTS_FILE):
        if path.exists():
            path.unlink()
            log.debug("Удалён файл прогресса: %s", path)
