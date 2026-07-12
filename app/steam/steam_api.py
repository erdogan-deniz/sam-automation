"""Получение данных через Steam Web API."""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("sam_automation")

BASE_URL = "https://api.steampowered.com"


class _RateLimitError(RuntimeError):
    """Исключение при превышении лимита запросов к Steam API (HTTP 429)."""


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
    except (OSError, http.client.HTTPException) as e:
        # RemoteDisconnected/ConnectionReset/IncompleteRead не оборачиваются в
        # URLError → без этого сырое исключение роняло весь scan/farm-прогон.
        raise RuntimeError(f"Сетевой сбой Steam API: {e}") from e
    except ValueError as e:
        # HTTP 200 с не-JSON телом (Cloudflare/капча) → JSONDecodeError/
        # UnicodeDecodeError (подклассы ValueError), не сетевой сбой.
        raise RuntimeError(f"Steam API вернул не-JSON ответ: {e}") from e


def fetch_owned_games(api_key: str, steam_id: str) -> list[dict]:
    """Получает список всех игр пользователя.

    Returns:
        Список словарей с ключами: appid, name, playtime_forever, ...
    """
    url = (
        f"{BASE_URL}/IPlayerService/GetOwnedGames/v1/"
        f"?key={api_key}&steamid={steam_id}"
        f"&include_appinfo=1&include_played_free_games=1"
        f"&skip_unvetted_apps=false"
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
