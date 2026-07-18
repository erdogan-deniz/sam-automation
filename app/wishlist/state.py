"""Resume-состояние авто-добавления каталога Steam в вишлист.

Зеркало app/free_games/state.py, свой каталог data/games/ids/wishlist/ (не
пересекается с free/achievements/cards/playtime).

  candidates.txt — universe минус owned/wishlisted/added/refused
  added.txt      — успешно добавлено (x-eresult=1) — skip
  refused.txt    — терминально (owned/уже-в-вишлисте/invalid) — skip
  error.txt      — транзиентная сетевая ошибка — восстановим --retry-errors
"""

from __future__ import annotations

from app.cache import GAMES_DIR
from app.id_file import (
    _append_id,
    _atomic_write_text,
    load_ids_file,
    read_ids_ordered,
)

_WISHLIST_DIR = GAMES_DIR / "ids" / "wishlist"

CANDIDATES_FILE = _WISHLIST_DIR / "candidates.txt"
ADDED_FILE = _WISHLIST_DIR / "added.txt"
REFUSED_FILE = _WISHLIST_DIR / "refused.txt"
ERROR_FILE = _WISHLIST_DIR / "error.txt"


def load_candidates() -> list[int]:
    """candidates.txt с сохранением порядка обнаружения (дедуп первых вхождений)."""
    return read_ids_ordered(CANDIDATES_FILE)


def save_candidates(appids: list[int]) -> None:
    """Атомарно перезаписывает candidates.txt (числовая сортировка, дедуп)."""
    _atomic_write_text(
        CANDIDATES_FILE, "\n".join(str(i) for i in sorted(set(appids))) + "\n"
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
