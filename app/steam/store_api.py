"""HTTP-запросы к Steam Store API (store.steampowered.com/api/appdetails)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("sam_automation")

_STORE_API = "https://store.steampowered.com/api/appdetails"
_TRADING_CARDS_CATEGORY = 29
_REQUEST_DELAY = 1.2  # секунд между запросами (Store API rate limit)


def _has_trading_cards(appid: int) -> bool | None:
    """Запрашивает Store API для одной игры.

    Returns:
        True если есть trading cards, False если нет, None при ошибке запроса.
    """
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
        return (
            False  # Store API вернул неожиданный формат (список вместо словаря)
        )

    categories = inner.get("categories", [])
    return any(cat.get("id") == _TRADING_CARDS_CATEGORY for cat in categories)


def fetch_achievement_count(appid: int) -> int | None:
    """Сколько достижений у игры по Store API.

    Returns:
        N   — блок achievements ЕСТЬ, total == N (включая 0).
        None — блок отсутствует / success=false / ошибка запроса = UNKNOWN.

    КРИТИЧНО: отсутствие блока (playtest/демо/регион-лок/снято с продажи)
    НЕ равно «0 достижений». Схлопывание unknown в 0 теряло игры с
    достижениями (откат каталога v1.1.0). Поэтому 0 только при явном total==0.
    """
    url = f"{_STORE_API}?appids={appid}&filters=achievements&l=english"
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
        return None  # приложение недоступно (DLC/удалено/регион) → unknown
    inner = app_data.get("data", {})
    if not isinstance(inner, dict):
        return None
    achievements = inner.get("achievements")
    if not isinstance(achievements, dict):
        return None  # блока нет → unknown (НЕ 0)
    total = achievements.get("total")
    if not isinstance(total, int):
        return None
    return total
