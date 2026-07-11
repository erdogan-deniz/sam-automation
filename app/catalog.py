"""Advisory-каталог достижений: раскладка библиотеки по данным Store API.

ВАЖНО — урок отката v1.1.0: классификация Store — это СОВЕТ, не основание для
пропуска. Только SAM (farm) вправе терминально пометить игру «без достижений»
(without.txt). Store ненадёжен (playtest/демо/регион-лок отдают пустой блок
achievements даже при реально существующих достижениях), поэтому:

- with.txt       — Store подтвердил достижения (>0): можно доверять как приоритету;
- store_zero.txt — Store сказал 0: СОВЕТ, farm этот файл НЕ читает → не пропускает;
- unknown        — не персистится: перезапрашивается в следующий прогон.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from .cache import DONE_IDS_FILE
from .id_file import _append_id, _remove_id, load_ids_file
from .steam.store_api import AchievementInfo

log = logging.getLogger("sam_automation")

# Каталог лежит рядом с прогресс-файлами достижений (achievements/).
_ACH_DIR = DONE_IDS_FILE.parent
WITH_FILE = _ACH_DIR / "with.txt"
STORE_ZERO_FILE = _ACH_DIR / "store_zero.txt"
STORE_EMPTY_FILE = _ACH_DIR / "store_empty.txt"


def classify_achievements(info: AchievementInfo) -> str:
    """Классифицирует игру по ответу Store API (advisory).

    Store не ответил → "unknown" (перезапрос); ответил без данных →
    "store_empty"; total==0 → "store_zero"; total>0 → "with".
    """
    if not info.responded:
        return "unknown"
    if info.total is None:
        return "store_empty"
    if info.total == 0:
        return "store_zero"
    return "with"


def load_with_ids() -> set[int]:
    """Читает with.txt → set[int] (Store-подтверждённые достижения)."""
    return load_ids_file(WITH_FILE)


def load_store_zero_ids() -> set[int]:
    """Читает store_zero.txt → set[int] (advisory «Store сказал 0»)."""
    return load_ids_file(STORE_ZERO_FILE)


def load_store_empty_ids() -> set[int]:
    """Читает store_empty.txt → set[int] (Store ответил без данных)."""
    return load_ids_file(STORE_EMPTY_FILE)


def mark_with(appid: int) -> None:
    """Дозаписывает appid в with.txt."""
    _append_id(WITH_FILE, appid)


def mark_store_zero(appid: int) -> None:
    """Дозаписывает appid в store_zero.txt."""
    _append_id(STORE_ZERO_FILE, appid)


def mark_store_empty(appid: int) -> None:
    """Дозаписывает appid в store_empty.txt."""
    _append_id(STORE_EMPTY_FILE, appid)


def unmark_store_advisory(appid: int) -> None:
    """Убирает appid из store_zero.txt и store_empty.txt (advisory-вердикт снят).

    No-op, если appid ни там, ни там. Зовётся, когда SAM выдал авторитетный
    вердикт по игре (разблокировал достижения ИЛИ подтвердил «без достижений»):
    ненадёжный Store-совет «0/пусто» больше не нужен — авторитет у without.txt.
    with.txt НЕ трогаем: это положительный сигнал, он не конфликтует.
    """
    _remove_id(STORE_ZERO_FILE, appid)
    _remove_id(STORE_EMPTY_FILE, appid)


def clear_catalog() -> None:
    """Удаляет with.txt, store_zero.txt и store_empty.txt."""
    for path in (WITH_FILE, STORE_ZERO_FILE, STORE_EMPTY_FILE):
        if path.exists():
            path.unlink()
            log.debug("Удалён каталог: %s", path)


def remaining_to_classify(
    all_ids: Iterable[int],
    with_ids: Iterable[int],
    zero_ids: Iterable[int],
    empty_ids: Iterable[int],
) -> list[int]:
    """Игры библиотеки, ещё не классифицированные (resume), отсортированы.

    unknown (транзиент) не персистится, поэтому из остатка исключаются
    with ∪ zero ∪ empty. Устаревшие id каталога вне библиотеки игнорируются.
    """
    classified = set(with_ids) | set(zero_ids) | set(empty_ids)
    return sorted(set(all_ids) - classified)


def prioritize_by_with(
    game_ids: list[int], with_ids: Iterable[int]
) -> list[int]:
    """Ставит игры из with.txt (Store подтвердил достижения) в начало списка.

    Относительный порядок внутри обеих групп сохраняется. advisory: состав
    списка НЕ меняется — только переупорядочивается, чтобы SAM сначала
    обрабатывал игры с гарантированными достижениями.
    """
    with_set = set(with_ids)
    prioritized = [gid for gid in game_ids if gid in with_set]
    rest = [gid for gid in game_ids if gid not in with_set]
    return prioritized + rest
