"""Состояние распродажи инвентаря: data/games/ids/inventory_sale/ (B-16).

Ключ — assetid предмета (id-файлы числовые, atomic-запись `app/id_file.py`).
Пишется СРАЗУ после каждого предмета: жёсткий килл не теряет сделанное.

listed.txt   — лот выставлен без подтверждения
pending.txt  — лот выставлен, ждёт подтверждения в мобильном Steam Guard
               (это НЕ «продано»: пока владелец не подтвердил, лота нет)
ground.txt   — разобран на самоцветы
refused.txt  — Steam отказал (терминал, повторно не пробуем)
Ошибки не записываются: предмет попробуют в следующем прогоне.
"""

from __future__ import annotations

from app.cache import GAMES_DIR
from app.id_file import _append_id, load_ids_file

_STATE_DIR = GAMES_DIR / "ids" / "inventory_sale"

LISTED_FILE = _STATE_DIR / "listed.txt"
PENDING_FILE = _STATE_DIR / "pending.txt"
GROUND_FILE = _STATE_DIR / "ground.txt"
REFUSED_FILE = _STATE_DIR / "refused.txt"


def _files() -> tuple:  # type: ignore[type-arg]
    return (LISTED_FILE, PENDING_FILE, GROUND_FILE, REFUSED_FILE)


def mark_listed(assetid: int) -> None:
    _append_id(LISTED_FILE, assetid)


def mark_pending(assetid: int) -> None:
    _append_id(PENDING_FILE, assetid)


def mark_ground(assetid: int) -> None:
    _append_id(GROUND_FILE, assetid)


def mark_refused(assetid: int) -> None:
    _append_id(REFUSED_FILE, assetid)


def load_listed() -> set[int]:
    return load_ids_file(LISTED_FILE)


def load_pending() -> set[int]:
    return load_ids_file(PENDING_FILE)


def load_handled() -> set[int]:
    """Все assetid, которые больше не трогаем."""
    handled: set[int] = set()
    for path in _files():
        handled |= load_ids_file(path)
    return handled


def reset() -> None:
    """Забыть всё сделанное (например, после снятия лотов)."""
    for path in _files():
        if path.exists():
            path.unlink()
