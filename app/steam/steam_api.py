"""Получение данных через Steam Web API."""

from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("sam_automation")

BASE_URL = "https://api.steampowered.com"

# Ретрай на HTTP 429: ограниченное число попыток, чтобы 1-2 rate-limit не роняли
# весь scan/boost-прогон, но и не крутились вечно по «злому» Retry-After.
_RATE_LIMIT_ATTEMPTS = 3  # всего попыток (1 исходная + 2 ретрая)
_RATE_LIMIT_DELAY = 2.0  # дефолтная пауза, если Retry-After не пришёл
_RATE_LIMIT_DELAY_CAP = 10.0  # потолок паузы (не ждём часами по заголовку)


class _RateLimitError(RuntimeError):
    """Исключение при превышении лимита запросов к Steam API (HTTP 429)."""

    def __init__(self, msg: str, retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


def _parse_retry_after(e: urllib.error.HTTPError) -> float | None:
    """Секунды из заголовка Retry-After (только числовой формат)."""
    ra = e.headers.get("Retry-After") if e.headers else None
    if ra and str(ra).strip().isdigit():
        return float(str(ra).strip())
    return None


def _api_get_once(url: str) -> dict:
    """Одна GET-попытка к Steam API. HTTP 429 → _RateLimitError (для ретрая)."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _RateLimitError(
                "Steam API rate limit (429)", _parse_retry_after(e)
            ) from e
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


def _api_get(url: str) -> dict:
    """GET к Steam API с ограниченным ретраем на HTTP 429.

    Только 429 ретраится (сетевые сбои/не-JSON от _api_get_once пробрасываются
    сразу — их лечит caller/верхний ретрай, не пауза). После исчерпания попыток
    отдаёт _RateLimitError, как раньше делал прямой путь.
    """
    for attempt in range(_RATE_LIMIT_ATTEMPTS):
        try:
            return _api_get_once(url)
        except _RateLimitError as e:
            if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                raise
            wait = (
                e.retry_after
                if e.retry_after is not None
                else _RATE_LIMIT_DELAY
            )
            wait = min(wait, _RATE_LIMIT_DELAY_CAP)
            log.warning(
                "Steam API 429 (попытка %d/%d) — жду %.0fс",
                attempt + 1,
                _RATE_LIMIT_ATTEMPTS,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")  # для mypy: цикл всегда вернёт/кинет


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
        else:
            # Steam изредка отдаёт game_count>0 с пустым списком games
            # (частичный/битый ответ) — раньше это был тихий return [].
            log.warning(
                "Steam API: game_count=%d, но список games пуст для %s",
                count,
                steam_id,
            )
        return []

    # Одна запись без валидного appid не должна ронять источник: потребитель
    # (scan/boost) обращается к g["appid"] напрямую → иначе KeyError на прогоне.
    valid = [g for g in games if g.get("appid") is not None]
    dropped = len(games) - len(valid)
    if dropped:
        log.warning(
            "Steam API: отброшено %d записей игр без валидного appid", dropped
        )

    return valid
