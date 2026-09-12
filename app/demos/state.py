"""Resume-состояние авто-добавления demo-версий игр Steam.

Зеркало app/free_games/state.py (2026-09-12, B-11) — свой каталог
data/games/ids/demos/, не пересекается с free_games/wishlist. Примитивы
id-файлов — из app.id_file (та же атомарная запись/дедуп).

  candidates.txt — обнаруженные кандидаты (вход фазы add)
  added.txt      — успешно выданные лицензии (granted)
  refused.txt    — CM отказал — ТЕРМИНАЛЬНО, skip-on-resume
  error.txt      — транзиентная ошибка — восстановим --retry-errors
"""

from __future__ import annotations

from app.cache import GAMES_DIR
from app.id_file import (
    _append_id,
    _atomic_write_text,
    load_ids_file,
    read_ids_ordered,
)

_DEMOS_DIR = GAMES_DIR / "ids" / "demos"

CANDIDATES_FILE = _DEMOS_DIR / "candidates.txt"
ADDED_FILE = _DEMOS_DIR / "added.txt"
REFUSED_FILE = _DEMOS_DIR / "refused.txt"
ERROR_FILE = _DEMOS_DIR / "error.txt"


def load_candidates() -> list[int]:
    """candidates.txt с сохранением порядка обнаружения (дедуп первых вхождений)."""
    return read_ids_ordered(CANDIDATES_FILE)


def save_candidates(appids: list[int]) -> None:
    """Атомарно перезаписывает candidates.txt, сохраняя порядок (дедуп первых
    вхождений) — числовая сортировка стёрла бы порядок обнаружения, на
    который полагается orchestrate.add()'s --limit (срез pending[:limit]).
    """
    _atomic_write_text(
        CANDIDATES_FILE,
        "\n".join(str(i) for i in dict.fromkeys(appids)) + "\n",
    )


def load_added_ids() -> set[int]:
    return load_ids_file(ADDED_FILE)


def load_refused_ids() -> set[int]:
    return load_ids_file(REFUSED_FILE)


def load_error_ids() -> set[int]:
    return load_ids_file(ERROR_FILE)


def mark_added(appid: int) -> None:
    _append_id(ADDED_FILE, appid)


def mark_refused(appid: int) -> None:
    _append_id(REFUSED_FILE, appid)


def mark_error(appid: int) -> None:
    _append_id(ERROR_FILE, appid)


def clear_error_ids() -> None:
    """Удаляет error.txt (для --retry-errors — только транзиент, НЕ refused)."""
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()


def clear_state() -> None:
    """Удаляет ВСЁ resume-состояние (--reset): candidates/added/refused/error."""
    for path in (CANDIDATES_FILE, ADDED_FILE, REFUSED_FILE, ERROR_FILE):
        if path.exists():
            path.unlink()
