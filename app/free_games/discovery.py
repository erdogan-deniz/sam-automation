"""Обнаружение бесплатного контента Steam по полному каталогу (B-19).

Каталог — IStoreService/GetAppList по типам контента, свойства —
IStoreBrowseService/GetItems: тот же путь, что у вишлиста
(app.wishlist.discovery), без витрины. Витрина резала выдачу и отвечала 429:
на 19.10.2026 в списках free/ было 1211 игр, а каталог дал около 29 тысяч
бесплатного не в библиотеке.

Правила отбора:
  * бесплатное (`is_free`) и уже вышедшее;
  * DLC и прочее с родительской игрой (`related_items.parent_appid`) —
    только к игре, которая есть в библиотеке (R-6: request_free_license
    выдаёт бесплатные DLC, живая проба 21.10.2026);
  * appid из exclude (уже в библиотеке, добавлено, отказано) в магазине не
    проверяется — так быстрее.
Демо в типизированных списках каталога нет — их добавляет add_demos.py.
"""

from __future__ import annotations

import logging

from app.wishlist import discovery as wl_discovery
from app.wishlist.content import ALL_TYPES, label

log = logging.getLogger("sam_automation")


def discover_candidates(
    *,
    api_key: str,
    types: frozenset[str] = ALL_TYPES,
    owned: set[int],
    exclude: set[int],
) -> list[int]:
    """Бесплатное вышедшее из каталога по types, кроме exclude.

    Сбой каталога или проверки магазина пробрасывается: orchestrate.discover
    тогда не перезаписывает candidates.txt неполным списком.
    """
    universe = wl_discovery.discover_universe(api_key, types=types)
    log.info("Steam: в каталоге (%s): %d", label(types), len(universe))
    todo = [a for a in universe if a not in exclude]
    log.info(
        "Steam: к проверке в магазине (минус owned/added/refused): %d",
        len(todo),
    )
    flags = wl_discovery.fetch_store_flags(todo)

    out: list[int] = []
    foreign = 0
    for appid in todo:
        if appid not in flags.free or appid in flags.coming_soon:
            continue
        parent = flags.parents.get(appid)
        if parent is not None and parent not in owned:
            foreign += 1
            continue
        out.append(appid)
    log.info(
        "Steam: бесплатного вышедшего %d, из них к играм не из библиотеки "
        "пропущено %d",
        len(out) + foreign,
        foreign,
    )
    return out
