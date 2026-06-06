"""Каталогизация игр по наличию достижений (для scan).

scan собирает все ID в all.txt; этот модуль раскидывает их на два списка —
with.txt (есть достижения) и without.txt (нет) — опрашивая Store API без
запуска SAM. Уже классифицированные игры (with/without, а также unlocked.txt
от farm) повторно не опрашиваются. То, что Store не нашёл (DLC, удалённые,
серверы), нигде не записывается и перепроверяется при следующем скане.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.cache import (
    load_done_ids,
    load_no_achievements_ids,
    load_with_achievements_ids,
    mark_no_achievements,
    mark_with_achievements,
)

log = logging.getLogger("sam_automation")

_REQUEST_DELAY = 1.2  # секунд между запросами (Store API rate limit)
_PROGRESS_EVERY = 25


def classify_count(count: int | None) -> str | None:
    """Категория по числу достижений: 'with', 'without' или None (не в Store)."""
    if count is None:
        return None
    return "with" if count > 0 else "without"


def select_unclassified(
    all_ids: list[int], known_with: set[int], known_without: set[int]
) -> list[int]:
    """ID из all_ids, которые ещё не разложены по with/without (порядок сохранён)."""
    known = known_with | known_without
    return [i for i in all_ids if i not in known]


def catalog(
    all_ids: list[int],
    fetch_count: Callable[[int], int | None],
    *,
    delay: float = _REQUEST_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Раскидывает all_ids на with/without через fetch_count.

    unlocked.txt (farm уже выбил достижения) считается за «с достижениями».
    Результат пишется в cache по мере получения — прерывание безопасно,
    следующий запуск продолжит с нерасклассифицированных.

    Returns:
        Счётчики обработанных за этот проход: {'with', 'without', 'unresolved'}.
    """
    known_with = load_with_achievements_ids() | load_done_ids()
    known_without = load_no_achievements_ids()
    todo = select_unclassified(all_ids, known_with, known_without)

    counts = {"with": 0, "without": 0, "unresolved": 0}
    total = len(todo)
    if not total:
        log.info("Каталог достижений: новых игр для классификации нет")
        return counts

    log.info("Каталог достижений: классифицирую %d игр через Store API", total)
    for n, appid in enumerate(todo):
        if n:
            sleep(delay)
        category = classify_count(fetch_count(appid))
        if category == "with":
            mark_with_achievements(appid)
            counts["with"] += 1
        elif category == "without":
            mark_no_achievements(appid)
            counts["without"] += 1
        else:
            counts["unresolved"] += 1

        done = n + 1
        if done % _PROGRESS_EVERY == 0 or done == total:
            log.info("  %d/%d", done, total)

    log.info(
        "Каталог достижений: с достижениями %d, без %d, не в Store %d",
        counts["with"],
        counts["without"],
        counts["unresolved"],
    )
    return counts
