"""Обнаружение бесплатных App ID Steam через неофициальный store search API.

Пагинация вынесена в app.steam.store_search (2026-09-12, переиспользуется
app/demos/discovery.py для категории Demos — та же логика бага не стоит
дублировать дважды).

Две категории (category1):
  998 = Games (дефолт витрины) + maxprice=free → F2P-игры
  994 = Software                + maxprice=free → бесплатные не-игровые app

Демо (category1=10) больше не обнаруживаются здесь — своим отдельным
скриптом, см. app/demos/discovery.py.

Потолок free-лицензий аккаунта ~1000-2000, поэтому набираем кандидатов с
запасом (target_count), а не весь каталог (~20k только по одной категории
Games+maxprice=free — см. total_count в живой проверке).
"""

from __future__ import annotations

import logging

from app.steam import store_search

log = logging.getLogger("sam_automation")

_CATEGORY_GAMES = 998
_CATEGORY_SOFTWARE = 994


def discover_candidates(
    *,
    target_count: int = 3000,
    page_size: int = 100,
    max_pages: int = 200,
) -> list[int]:
    """Собирает кандидатов на бесплатное добавление из витрины Steam.

    Два источника: F2P-игры (category1=998+maxprice=free), бесплатные
    не-игровые app (category1=994+maxprice=free). Дедуп между источниками.
    Не гарантирует полноту каталога — набирает достаточно кандидатов с
    запасом относительно потолка free-лицензий аккаунта (~1000-2000).
    """
    seen: set[int] = set()
    out: list[int] = []

    def _merge(ids: list[int]) -> None:
        for appid in ids:
            if appid not in seen:
                seen.add(appid)
                out.append(appid)

    log.info("Store search: обнаружение F2P-игр (maxprice=free)")
    _merge(
        store_search.collect_category(
            category1=_CATEGORY_GAMES,
            maxprice_free=True,
            target_count=target_count,
            page_size=page_size,
            max_pages=max_pages,
        )
    )
    log.info("Store search: найдено кандидатов (игры): %d", len(out))

    log.info("Store search: обнаружение бесплатных приложений")
    _merge(
        store_search.collect_category(
            category1=_CATEGORY_SOFTWARE,
            maxprice_free=True,
            target_count=target_count,
            page_size=page_size,
            max_pages=max_pages,
        )
    )
    log.info("Store search: найдено кандидатов (игры+app): %d", len(out))

    return out
