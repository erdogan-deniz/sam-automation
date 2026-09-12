"""Пагинация неофициального store search API Steam (по категориям).

Источник — store.steampowered.com/search/results/ (используется самим
сторефронтом для живого поиска; официально Valve его не документирует).
Проверено вживую (2026-07-17): count=100 — макс. размер страницы, пагинация
через start/count работает, total_count в ответе — общее число совпадений.

Вынесено из app/free_games/discovery.py (2026-09-12): чистый Store-API
примитив без free_games-специфики, переиспользуется app/demos/discovery.py
для категории Demos. Один источник правды для сетевого хардненинга —
будущий баг чинится в одном месте, а не в двух копиях.

Ретрай на 429/сеть — свой, не через app.steam.steam_api._api_get: другой
хост (store vs api.steampowered.com) и другая форма ответа (results_html,
не типизированный JSON) — reuse через приватные символы неродственного
модуля добавил бы связность без реальной экономии (~10 строк).
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("sam_automation")

_SEARCH_URL = "https://store.steampowered.com/search/results/"
_USER_AGENT = "Mozilla/5.0 (sam-automation)"

_APPID_RE = re.compile(r'data-ds-appid="(\d+)"')

# Ограниченный ретрай на 429 — не крутимся вечно на "злом" ответе витрины.
_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0
_PAGE_DELAY = 0.5  # пауза между страницами — не долбить витрину без нужды


def search_page(
    *, category1: int, start: int, count: int, maxprice_free: bool
) -> tuple[list[int], int]:
    """Одна страница store search. Возвращает (appids, total_count).

    Сетевой/JSON сбой после исчерпания ретраев → ([], 0), не исключение —
    вызывающая пагинация (collect_category) трактует пустой список как
    конец результатов (частичная выборка допустима, полнота не обещана).
    """
    params = (
        f"query&start={start}&count={count}&category1={category1}"
        f"&supportedlang=english&json=1&infinite=1"
    )
    if maxprice_free:
        params += "&maxprice=free"
    url = f"{_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    for attempt in range(_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results_html = data.get("results_html") or ""
            total_count_raw = data.get("total_count") or 0
            appids = [int(m) for m in _APPID_RE.findall(results_html)]
            return appids, int(total_count_raw)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < _RETRY_ATTEMPTS - 1:
                log.warning(
                    "Store search 429 (попытка %d/%d) — жду %.0fс",
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                    _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
                continue
            log.warning("Store search вернул %s: %s", e.code, e.reason)
            return [], 0
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            log.warning("Store search сетевой сбой: %s", e)
            return [], 0
        except (ValueError, TypeError) as e:
            log.warning("Store search вернул неожиданный ответ: %s", e)
            return [], 0
    return [], 0  # недостижимо (цикл всегда return'ит) — для mypy


def collect_category(
    *,
    category1: int,
    maxprice_free: bool,
    target_count: int,
    page_size: int,
    max_pages: int,
) -> list[int]:
    """Пагинирует одну категорию до target_count кандидатов или конца/max_pages."""
    seen: set[int] = set()
    out: list[int] = []
    start = 0
    for _page in range(max_pages):
        appids, total_count = search_page(
            category1=category1,
            start=start,
            count=page_size,
            maxprice_free=maxprice_free,
        )
        if not appids:
            break  # пустая страница — конец результатов ИЛИ сбой (уже залогирован)
        for appid in appids:
            if appid not in seen:
                seen.add(appid)
                out.append(appid)
        start += page_size
        if len(out) >= target_count or start >= total_count:
            break
        time.sleep(_PAGE_DELAY)
    return out
