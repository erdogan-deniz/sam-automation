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
from .id_file import _append_id, load_ids_file

log = logging.getLogger("sam_automation")

# Каталог лежит рядом с прогресс-файлами достижений (achievements/).
_ACH_DIR = DONE_IDS_FILE.parent
WITH_FILE = _ACH_DIR / "with.txt"
STORE_ZERO_FILE = _ACH_DIR / "store_zero.txt"


def classify_achievements(count: int | None) -> str:
    """Классифицирует игру по числу достижений из Store API (advisory).

    None → "unknown" (Store недоступен), 0 → "store_zero" (совет), >0 → "with".
    """
    if count is None:
        return "unknown"
    if count == 0:
        return "store_zero"
    return "with"


def load_with_ids() -> set[int]:
    """Читает with.txt → set[int] (Store-подтверждённые достижения)."""
    return load_ids_file(WITH_FILE)


def load_store_zero_ids() -> set[int]:
    """Читает store_zero.txt → set[int] (advisory «Store сказал 0»)."""
    return load_ids_file(STORE_ZERO_FILE)


def mark_with(appid: int) -> None:
    """Дозаписывает appid в with.txt."""
    _append_id(WITH_FILE, appid)


def mark_store_zero(appid: int) -> None:
    """Дозаписывает appid в store_zero.txt."""
    _append_id(STORE_ZERO_FILE, appid)


def clear_catalog() -> None:
    """Удаляет with.txt и store_zero.txt (для повторной каталогизации)."""
    for path in (WITH_FILE, STORE_ZERO_FILE):
        if path.exists():
            path.unlink()
            log.debug("Удалён каталог: %s", path)


def remaining_to_classify(
    all_ids: Iterable[int],
    with_ids: Iterable[int],
    zero_ids: Iterable[int],
) -> list[int]:
    """Игры библиотеки, ещё не классифицированные (resume), отсортированы.

    unknown не персистится, поэтому из остатка исключаются только with ∪ zero.
    Устаревшие id каталога вне библиотеки игнорируются.
    """
    classified = set(with_ids) | set(zero_ids)
    return sorted(set(all_ids) - classified)
