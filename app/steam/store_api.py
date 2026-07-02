"""HTTP-запросы к Steam Store API (store.steampowered.com/api/appdetails)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import NamedTuple

log = logging.getLogger("sam_automation")

_STORE_API = "https://store.steampowered.com/api/appdetails"


class AchievementInfo(NamedTuple):
    """Исход запроса достижений к Store API.

    total     — число достижений, если блок ЕСТЬ (включая 0); иначе None.
    responded — Store ОТВЕТИЛ (пусть и без данных): True. Транзиентная ошибка
                сети/HTTP (нужен ретрай): False.
    """

    total: int | None
    responded: bool


def fetch_achievement_info(appid: int) -> AchievementInfo:
    """Запрашивает число достижений игры у Store API.

    КРИТИЧНО (урок отката v1.1.0): отсутствие блока achievements
    (playtest/демо/регион-лок/снято с продажи) НЕ равно «0 достижений». Поэтому:
      - total=N, responded=True   — блок есть (0 только при явном total==0);
      - total=None, responded=True — Store ответил, но данных нет (data:[]/
        success=false) → стабильный store_empty (advisory, перезапрос не нужен);
      - total=None, responded=False — ошибка сети/HTTP → нужен ретрай.
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
        return AchievementInfo(None, responded=False)
    except Exception:
        return AchievementInfo(None, responded=False)

    app_data = data.get(str(appid), {})
    if not app_data.get("success"):
        return AchievementInfo(
            None, responded=True
        )  # страницы нет (DLC/регион)
    inner = app_data.get("data", {})
    if not isinstance(inner, dict):
        return AchievementInfo(None, responded=True)  # data:[] и т.п.
    achievements = inner.get("achievements")
    if not isinstance(achievements, dict):
        return AchievementInfo(None, responded=True)  # блока нет
    total = achievements.get("total")
    if not isinstance(total, int):
        return AchievementInfo(None, responded=True)
    return AchievementInfo(total, responded=True)
