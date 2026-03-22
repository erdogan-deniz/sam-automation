"""Определение наличия Steam Trading Cards через Store API.

Проверяет категорию 29 («Steam Trading Cards») для каждой игры.
Результаты кэшируются в двух txt-файлах — вечно, наличие
карточек в игре не меняется после релиза.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger("sam_automation")

_DATA_DIR = Path(__file__).parent.parent / "data" / "cards"
_HAS_CARDS_FILE = _DATA_DIR / "has_cards_ids.txt"
_NO_CARDS_FILE  = _DATA_DIR / "no_cards_ids.txt"

_STORE_API = "https://store.steampowered.com/api/appdetails"
_TRADING_CARDS_CATEGORY = 29
_REQUEST_DELAY = 1.2   # секунд между запросами (Store API rate limit)
_LOG_EVERY = 25        # логировать прогресс каждые N игр


def _read_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    result: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                result.add(int(line))
            except ValueError:
                log.warning("Невалидная строка в %s: %r", path, line)
    return result


def _load_cache() -> dict[int, bool]:
    cache: dict[int, bool] = {}
    for appid in _read_ids(_HAS_CARDS_FILE):
        cache[appid] = True
    for appid in _read_ids(_NO_CARDS_FILE):
        cache[appid] = False
    return cache


def _save_cache(cache: dict[int, bool]) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    has = sorted(k for k, v in cache.items() if v)
    no  = sorted(k for k, v in cache.items() if not v)
    _HAS_CARDS_FILE.write_text("\n".join(str(i) for i in has), encoding="utf-8")
    _NO_CARDS_FILE.write_text("\n".join(str(i) for i in no),  encoding="utf-8")


def _has_trading_cards(appid: int) -> bool | None:
    """Запрашивает Store API для одной игры. Возвращает None при ошибке."""
    url = f"{_STORE_API}?appids={appid}&filters=categories&l=english"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log.warning("Store API: rate limit, жду 30с...")
            time.sleep(30)
        return None
    except Exception:
        return None

    app_data = data.get(str(appid), {})
    if not app_data.get("success"):
        return False  # приложение не найдено (DLC, удалено и т.д.)

    inner = app_data.get("data", {})
    if not isinstance(inner, dict):
        return False  # Store API вернул неожиданный формат (список вместо словаря)
    categories = inner.get("categories", [])
    return any(cat.get("id") == _TRADING_CARDS_CATEGORY for cat in categories)


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
            total, len(cache), max(1, total * _REQUEST_DELAY // 60),
        )

    for i, appid in enumerate(unchecked, 1):
        result = _has_trading_cards(appid)
        if result is not None:
            cache[appid] = result
        # Сохраняем кэш каждые 50 игр чтобы не потерять прогресс
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
        len(result_ids), len(app_ids),
    )
    return result_ids
