"""Получение данных через Steam Web API."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

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


from .steam_id import resolve_steam_id  # noqa: E402


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
            log.warning(
                "У аккаунта %s нет игр (или профиль приватный)", steam_id
            )
        return []

    return games


def fetch_all_game_ids(api_key: str, steam_id_or_url: str) -> list[int]:
    """Получает App ID ВСЕХ игр пользователя одним запросом (быстро).

    Включает демо, ПО и всё что есть в библиотеке.
    Не проверяет достижения — обработка займёт секунды вместо минут.
    """
    steam_id = resolve_steam_id(api_key, steam_id_or_url)

    games = fetch_owned_games(api_key, steam_id)
    if not games:
        return []

    ids = [g["appid"] for g in games]
    log.info("Найдено %d ID приложений библиотеки Steam через Steam API", len(ids))
    return ids


def fetch_badge_app_ids(api_key: str, steam_id: str) -> set[int]:
    """Возвращает appid всех игр, для которых у аккаунта есть хоть какой-то значок.

    Использует IPlayerService/GetBadges. Нужен для метода A в detect_card_drops.py.
    """
    url = (
        f"{BASE_URL}/IPlayerService/GetBadges/v1"
        f"?key={api_key}&steamid={steam_id}"
    )
    try:
        data = _api_get(url)
        badges = data.get("response", {}).get("badges", [])
        return {b["appid"] for b in badges if "appid" in b}
    except Exception as e:
        log.warning("IPlayerService/GetBadges: %s", e)
        return set()
