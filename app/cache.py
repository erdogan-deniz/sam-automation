"""Кэш результатов API-сканирования и прогресса обработки."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("sam_automation")

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

# Текстовые файлы состояния
ALL_IDS_FILE = DATA_DIR / "all_ids.txt"
DONE_IDS_FILE = DATA_DIR / "done_ids.txt"
ERROR_IDS_FILE = DATA_DIR / "error_ids.txt"
NO_ACHIEVEMENTS_FILE = DATA_DIR / "no_achievements_ids.txt"


# ---------------------------------------------------------------------------
# Текстовые файлы прогресса
# ---------------------------------------------------------------------------

def _load_ids_file(path: Path) -> set[int]:
    """Читает текстовый файл с ID (по одному на строку) → set[int]."""
    if not path.exists():
        return set()
    result: set[int] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    result.add(int(line))
                except ValueError:
                    log.warning("Невалидная строка в %s: %r", path, line)
    except Exception as e:
        log.warning("Не удалось прочитать %s: %s", path, e)
    return result


def _append_id(path: Path, game_id: int) -> None:
    """Дозаписывает один ID в конец файла."""
    path.parent.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{game_id}\n")


def load_done_ids() -> set[int]:
    """Читает done_ids.txt → set[int]."""
    return _load_ids_file(DONE_IDS_FILE)


def load_error_ids() -> set[int]:
    """Читает error_ids.txt → set[int]."""
    return _load_ids_file(ERROR_IDS_FILE)


def mark_done(game_id: int) -> None:
    """Дозаписывает game_id в done_ids.txt."""
    _append_id(DONE_IDS_FILE, game_id)


def mark_error_id(game_id: int) -> None:
    """Дозаписывает game_id в error_ids.txt."""
    _append_id(ERROR_IDS_FILE, game_id)


def load_no_achievements_ids() -> set[int]:
    """Читает no_achievements_ids.txt → set[int]."""
    return _load_ids_file(NO_ACHIEVEMENTS_FILE)


def mark_no_achievements(game_id: int) -> None:
    """Дозаписывает game_id в no_achievements_ids.txt."""
    _append_id(NO_ACHIEVEMENTS_FILE, game_id)


def clear_progress() -> None:
    """Удаляет done_ids.txt, error_ids.txt и no_achievements_ids.txt (для нового полного запуска)."""
    for path in (DONE_IDS_FILE, ERROR_IDS_FILE, NO_ACHIEVEMENTS_FILE):
        if path.exists():
            path.unlink()
            log.debug("Удалён файл прогресса: %s", path)
