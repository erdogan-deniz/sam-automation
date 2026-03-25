"""Определение наличия Steam Trading Cards через Store API.

Проверяет категорию 29 («Steam Trading Cards») для каждой игры.
Результаты кэшируются в двух txt-файлах — вечно, наличие
карточек в игре не меняется после релиза.
"""

from __future__ import annotations

import logging
import time

from ..cache import CARDS_DIR
from ..id_file import load_ids_file
from app.steam.store_api import _REQUEST_DELAY, _has_trading_cards

log = logging.getLogger("sam_automation")

_HAS_CARDS_FILE = CARDS_DIR / "has_cards_ids.txt"
_NO_CARDS_FILE = CARDS_DIR / "no_cards_ids.txt"

_LOG_EVERY = 25  # логировать прогресс каждые N игр


def _load_cache() -> dict[int, bool]:
    """Читает кэш из has_cards_ids.txt и no_cards_ids.txt → {appid: bool}."""
    cache: dict[int, bool] = {}
    for appid in load_ids_file(_HAS_CARDS_FILE):
        cache[appid] = True
    for appid in load_ids_file(_NO_CARDS_FILE):
        cache[appid] = False
    return cache


def _save_cache(cache: dict[int, bool]) -> None:
    """Сохраняет кэш trading cards в два отдельных txt-файла."""
    CARDS_DIR.mkdir(exist_ok=True)
    has = sorted(k for k, v in cache.items() if v)
    no = sorted(k for k, v in cache.items() if not v)
    _HAS_CARDS_FILE.write_text("\n".join(str(i) for i in has), encoding="utf-8")
    _NO_CARDS_FILE.write_text("\n".join(str(i) for i in no), encoding="utf-8")


def get_games_with_cards(app_ids: list[int]) -> list[int]:
    """Возвращает app_ids у которых есть Steam Trading Cards.

    Проверяет Store API для игр не в кэше, кэширует результат.
    Первый запуск для 1500+ игр займёт ~30 минут.
    """
    cache = _load_cache()

    unchecked = [aid for aid in app_ids if aid not in cache]
    total = len(unchecked)

    if unchecked:
        log.info(
            "Проверяю наличие карточек для %d игр (в кэше: %d). "
            "Это займёт ~%d мин при первом запуске...",
            total,
            len(cache),
            max(1, total * _REQUEST_DELAY // 60),
        )

    for i, appid in enumerate(unchecked, 1):
        result = _has_trading_cards(appid)
        if result is not None:
            cache[appid] = result
        if i % 50 == 0:
            _save_cache(cache)
        if i % _LOG_EVERY == 0 or i == total:
            log.info("Прогресс: %d/%d игр проверено", i, total)
        if i < total:
            time.sleep(_REQUEST_DELAY)

    if unchecked:
        _save_cache(cache)

    result_ids = [aid for aid in app_ids if cache.get(aid, False)]
    log.info(
        "Игр с trading cards: %d из %d проверенных",
        len(result_ids),
        len(app_ids),
    )
    return result_ids
