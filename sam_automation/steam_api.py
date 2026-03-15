"""Получение списка игр пользователя через Steam Web API."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
import urllib.error

log = logging.getLogger("sam_automation")

BASE_URL = "https://api.steampowered.com"


class _RateLimitError(RuntimeError):
    """Steam API rate limit (429)."""


def _api_get(url: str) -> dict:
    """Выполняет GET-запрос к Steam API и возвращает JSON."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _RateLimitError("Steam API rate limit (429)") from e
        raise RuntimeError(f"Steam API вернул {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ошибка подключения к Steam API: {e.reason}") from e


def resolve_vanity_url(api_key: str, vanity_name: str) -> str:
    """Резолвит vanity URL (кастомное имя профиля) в Steam ID 64.

    Пример: 'gabelogannewell' → '76561197960287930'
    """
    url = (
        f"{BASE_URL}/ISteamUser/ResolveVanityURL/v1/"
        f"?key={api_key}&vanityurl={vanity_name}"
    )
    data = _api_get(url)
    resp = data.get("response", {})

    if resp.get("success") != 1:
        raise RuntimeError(
            f"Не удалось резолвить vanity URL '{vanity_name}': "
            f"{resp.get('message', 'unknown error')}"
        )

    return resp["steamid"]


def resolve_steam_id(api_key: str, steam_id_or_url: str) -> str:
    """Принимает Steam ID 64, vanity name или полный URL профиля → возвращает Steam ID 64."""
    # Уже числовой Steam ID 64
    if re.fullmatch(r"\d{17}", steam_id_or_url):
        return steam_id_or_url

    # URL вида steamcommunity.com/id/vanityname или /profiles/76561...
    m = re.search(r"steamcommunity\.com/id/([^/?\s]+)", steam_id_or_url)
    if m:
        return resolve_vanity_url(api_key, m.group(1))

    m = re.search(r"steamcommunity\.com/profiles/(\d{17})", steam_id_or_url)
    if m:
        return m.group(1)

    # Считаем vanity name
    return resolve_vanity_url(api_key, steam_id_or_url)


def fetch_owned_games(api_key: str, steam_id: str) -> list[dict]:
    """Получает список всех игр пользователя.

    Returns:
        Список словарей с ключами: appid, name, playtime_forever, ...
    """
    url = (
        f"{BASE_URL}/IPlayerService/GetOwnedGames/v1/"
        f"?key={api_key}&steamid={steam_id}"
        f"&include_appinfo=1&include_played_free_games=1"
        f"&format=json"
    )

    data = _api_get(url)
    resp = data.get("response", {})
    games = resp.get("games", [])

    if not games:
        count = resp.get("game_count", 0)
        if count == 0:
            log.warning("У аккаунта %s нет игр (или профиль приватный)", steam_id)
        return []

    log.info("Получено %d игр для аккаунта %s", len(games), steam_id)
    return games


def fetch_all_game_ids(api_key: str, steam_id_or_url: str) -> list[int]:
    """Получает App ID ВСЕХ игр пользователя одним запросом (быстро).

    Включает демо, ПО и всё что есть в библиотеке.
    Не проверяет достижения — обработка займёт секунды вместо минут.
    """
    steam_id = resolve_steam_id(api_key, steam_id_or_url)
    log.info("Steam ID: %s", steam_id)

    games = fetch_owned_games(api_key, steam_id)
    if not games:
        return []

    ids = [g["appid"] for g in games]
    log.info("Получено %d игр из библиотеки (без проверки достижений)", len(ids))
    return ids
