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
# Тот же бюджет попыток делят транзиентные сетевые сбои (см. ниже).
_RATE_LIMIT_ATTEMPTS = 3  # всего попыток (1 исходная + 2 ретрая)
_RATE_LIMIT_DELAY = 2.0  # дефолтная пауза, если Retry-After не пришёл
_RATE_LIMIT_DELAY_CAP = 10.0  # потолок паузы (не ждём часами по заголовку)

# Ретрай на транзиентный сетевой сбой (SSL-обрыв/сброс соединения — НЕ
# HTTP-код от сервера). Живая находка 2026-07-19: одиночный SSL EOF на любой
# из ~5 страниц GetAppList ронял всю пагинацию каталога вишлиста без единого
# повтора. Retry-After здесь взять неоткуда (это не HTTP-ответ) — фиксированная
# короткая пауза, в отличие от 429 (тот уважает заголовок).
_NETWORK_RETRY_DELAY = 2.0


class _RateLimitError(RuntimeError):
    """Исключение при превышении лимита запросов к Steam API (HTTP 429)."""

    def __init__(self, msg: str, retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


class _TransientNetworkError(RuntimeError):
    """Транзиентный сетевой сбой (SSL/обрыв соединения) — стоит повторить."""


def _parse_retry_after(e: urllib.error.HTTPError) -> float | None:
    """Секунды из заголовка Retry-After (только числовой формат)."""
    ra = e.headers.get("Retry-After") if e.headers else None
    if ra and str(ra).strip().isdigit():
        return float(str(ra).strip())
    return None


def _api_get_once(url: str) -> dict:
    """Одна GET-попытка к Steam API.

    HTTP 429 → _RateLimitError; URLError/OSError/HTTPException (SSL-обрыв,
    сброс соединения — транспортный сбой, не ответ сервера) →
    _TransientNetworkError. Оба ретраятся в _api_get.
    """
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
        raise _TransientNetworkError(
            f"Ошибка подключения к Steam API: {e.reason}"
        ) from e
    except (OSError, http.client.HTTPException) as e:
        # RemoteDisconnected/ConnectionReset/IncompleteRead не оборачиваются в
        # URLError → без этого сырое исключение роняло весь scan/farm-прогон.
        raise _TransientNetworkError(f"Сетевой сбой Steam API: {e}") from e
    except ValueError as e:
        # HTTP 200 с не-JSON телом (Cloudflare/капча) → JSONDecodeError/
        # UnicodeDecodeError (подклассы ValueError), не сетевой сбой.
        raise RuntimeError(f"Steam API вернул не-JSON ответ: {e}") from e


def _api_get(url: str) -> dict:
    """GET к Steam API с ограниченным ретраем на HTTP 429 и на транзиентные
    сетевые сбои (SSL/обрыв соединения).

    Оба класса ошибок делят один бюджет попыток (_RATE_LIMIT_ATTEMPTS).
    Сетевой сбой ждёт фиксированную _NETWORK_RETRY_DELAY (Retry-After здесь
    взять неоткуда, в отличие от 429). Не-JSON и прочие HTTP-коды (кроме 429)
    — это реальный ответ сервера, не транспортный сбой, поэтому НЕ ретраятся.
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
        except _TransientNetworkError as e:
            if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                raise
            log.warning(
                "Steam API: транзиентный сетевой сбой (попытка %d/%d) — "
                "жду %.0fс: %s",
                attempt + 1,
                _RATE_LIMIT_ATTEMPTS,
                _NETWORK_RETRY_DELAY,
                e,
            )
            time.sleep(_NETWORK_RETRY_DELAY)
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
