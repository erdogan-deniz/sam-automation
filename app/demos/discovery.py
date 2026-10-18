"""Обнаружение demo App ID Steam через неофициальный store search API.

Пагинация — app.steam.store_search (общий с app/free_games/discovery.py
Store-API примитив). Единственная категория:
  10 = Demos (демо всегда бесплатны — maxprice=free НЕ нужен и не запрашивается)

Потолок free-лицензий аккаунта ~1000-2000 общий с free_games — набираем
кандидатов с запасом (target_count), а не весь каталог демо.
"""

from __future__ import annotations

import logging

from app.steam import store_search

log = logging.getLogger("sam_automation")

_CATEGORY_DEMOS = 10


def discover_candidates(
    *,
    target_count: int = 3000,
    page_size: int = 100,
    max_pages: int = 200,
) -> list[int]:
    """Собирает кандидатов на добавление demo из витрины Steam.

    Единственный источник — категория Demos. Не гарантирует полноту каталога
    — набирает достаточно кандидатов с запасом относительно потолка
    free-лицензий аккаунта.
    """
    log.info("Store search: обнаружение демо")
    found = store_search.collect_category(
        category1=_CATEGORY_DEMOS,
        maxprice_free=False,
        target_count=target_count,
        page_size=page_size,
        max_pages=max_pages,
    )
    out = list(dict.fromkeys(found))
    log.info("Store search: найдено кандидатов (демо): %d", len(out))
    return out
