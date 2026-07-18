"""Обнаружение вселенной кандидатов Steam для вишлиста (GetAppList).

GetAppList и GetWishlist (Task 5) — оба на api.steampowered.com с типизированным
JSON-ответом: тот же хост и форма, что уже обрабатывает
app/steam/steam_api.py::_api_get (429-ретрай с Retry-After). В отличие от
app/free_games/discovery.py (store.steampowered.com, HTML results_html) здесь
реюз ЧЕРЕЗ приватный _api_get оправдан — не дублируем retry-логику ради ~10
одинаковых строк.
"""

from __future__ import annotations

import logging

from app.steam.steam_api import BASE_URL, _api_get

log = logging.getLogger("sam_automation")

_MAX_RESULTS = 50000  # максимум GetAppList/v1 на страницу


def _fetch_universe_page(
    api_key: str, *, last_appid: int, max_results: int = _MAX_RESULTS
) -> tuple[list[int], bool, int]:
    """Одна страница GetAppList/v1 (все типы контента).

    Возвращает (appids, have_more_results, следующий last_appid).
    """
    url = (
        f"{BASE_URL}/IStoreService/GetAppList/v1/?key={api_key}"
        f"&include_games=1&include_dlc=1&include_software=1"
        f"&include_videos=1&include_hardware=1"
        f"&max_results={max_results}&last_appid={last_appid}"
    )
    data = _api_get(url)
    resp = data.get("response", {})
    apps = resp.get("apps", [])
    appids = [int(a["appid"]) for a in apps if a.get("appid") is not None]
    have_more = bool(resp.get("have_more_results", False))
    next_last_appid = int(resp.get("last_appid", last_appid))
    return appids, have_more, next_last_appid


def discover_universe(api_key: str, *, max_pages: int = 200) -> list[int]:
    """Пагинирует GetAppList/v1 до конца каталога (games+dlc+software+videos+hardware).

    max_pages — защита от зависания, если Steam когда-либо вернёт
    have_more_results=True с незменяющимся курсором.
    """
    out: list[int] = []
    last_appid = 0
    for _page in range(max_pages):
        appids, have_more, last_appid = _fetch_universe_page(
            api_key, last_appid=last_appid
        )
        if not appids:
            break
        out.extend(appids)
        if not have_more:
            break
    return out
