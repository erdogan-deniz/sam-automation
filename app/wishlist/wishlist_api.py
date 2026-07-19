"""Добавление в Wishlist Steam через IWishlistService (модерн WebAPI).

Write-путь снят ЖИВЬЁМ на реальном аккаунте 2026-07-18 (см. дизайн-спеку):
POST api.steampowered.com/IWishlistService/AddToWishlist/v1/?access_token=<JWT>
форма appid=<id>. access_token = community-JWT из app.cookies.get_web_cookies
(aud=["web:community"] — этого достаточно, sessionid/CSRF/store-cookie НЕ
нужны — легаси store-эндпоинт отклонён именно потому, что требует
web:store-aud токен, которого get_web_cookies не даёт).

Классификатор — по HTTP-заголовку x-eresult (authoritative WebAPI-сигнал),
числа совпадают с steam.enums.EResult (OK=1, Fail=2, InvalidParam=8,
RateLimitExceeded=84), но сам enum-класс здесь НЕ импортируется: это другой
транспорт (HTTP-заголовок WebAPI, не CM-протокол), а `steam`-пакет тяжёлый
(gevent/protobuf) — тянуть его в модуль, которому нужны только эти 4 числа,
не оправдано (тот же расчёт, что в app/free_games/discovery.py — не
реюзать через приватные символы неродственного транспорта без реальной
экономии).
"""

from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger("sam_automation")

BASE_URL = "https://api.steampowered.com"

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded; charset=UTF-8"

_ERESULT_OK = "1"  # steam.enums.EResult.OK
_ERESULT_FAIL = "2"  # steam.enums.EResult.Fail (owned / уже-в-вишлисте)
_ERESULT_INVALID_PARAM = "8"  # EResult.InvalidParam (delisted/несуществующий)
_ERESULT_RATE_LIMIT = "84"  # EResult.RateLimitExceeded

Classification = Literal["added", "refused", "rate_limit", "auth_fail"]


@dataclass
class AddResult:
    """Итог одного прогона добавления в вишлист."""

    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_wall: bool = False
    auth_fail: bool = False


def _classify(http_status: int, eresult: str | None) -> Classification:
    """Классифицирует ответ IWishlistService по HTTP-статусу + x-eresult.

    Таблица снята вживую 2026-07-18: 1→added; 2 (Fail, owned/уже-в-вишлисте) и
    8 (InvalidParam, delisted/несуществующий) → refused (терминал); голый HTTP
    429 (заголовок мог не прийти) либо eresult=84 (RateLimitExceeded) →
    rate_limit; HTTP 401 → auth_fail (сессия истекла/невалидна).
    """
    if http_status == 401:
        return "auth_fail"
    if http_status == 429 or eresult == _ERESULT_RATE_LIMIT:
        return "rate_limit"
    if eresult == _ERESULT_OK:
        return "added"
    return (
        "refused"  # включая eresult в (_ERESULT_FAIL, _ERESULT_INVALID_PARAM)
    )


# Ретрай на транзиентный сетевой сбой (SSL-обрыв/таймаут хендшейка — НЕ
# HTTP-ответ сервера). Живая находка 2026-07-19 (10k-прогон): единичные SSL
# EOF/timeout на AddToWishlist уходили прямиком в error.txt без единой
# попытки повтора — в отличие от app/steam/steam_api._api_get (тот же класс
# сбоя там уже ретраится), здесь ретрая не было вовсе. Бюджет короткий (1
# повтор) — add_pending и так не ретраит error бесконечно по design.
_NETWORK_RETRY_ATTEMPTS = 2  # 1 исходная попытка + 1 ретрай
_NETWORK_RETRY_DELAY = 1.0


def _call(
    action: str, appid: int, access_token: str
) -> tuple[int, str | None, dict[str, Any]]:
    """POST IWishlistService/<action>/v1/. Возвращает (http_status, x-eresult, body).

    HTTPError (валидный http_status от сервера) не ретраится — это реальный
    ответ, не транспортный сбой. URLError/OSError/HTTPException (SSL-обрыв,
    таймаут хендшейка) ретраятся _NETWORK_RETRY_ATTEMPTS раз с фиксированной
    паузой; исчерпав бюджет — пробрасываются наверх, add_pending() ловит их
    как error-исход для конкретного appid (не ретраит дальше, переходит к
    следующему).
    """
    url = (
        f"{BASE_URL}/IWishlistService/{action}/v1/?access_token={access_token}"
    )
    data = urllib.parse.urlencode({"appid": appid}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": _FORM_CONTENT_TYPE}
    )
    for attempt in range(_NETWORK_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                eresult = resp.headers.get("x-eresult")
                try:
                    body: dict[str, Any] = json.loads(
                        resp.read().decode("utf-8")
                    )
                except (ValueError, UnicodeDecodeError):
                    body = {}
                return resp.status, eresult, body
        except urllib.error.HTTPError as e:
            eresult = e.headers.get("x-eresult") if e.headers else None
            return e.code, eresult, {}
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            if attempt == _NETWORK_RETRY_ATTEMPTS - 1:
                raise
            log.warning(
                "Wishlist: транзиентный сетевой сбой на appid=%d "
                "(попытка %d/%d) — жду %.0fс: %s",
                appid,
                attempt + 1,
                _NETWORK_RETRY_ATTEMPTS,
                _NETWORK_RETRY_DELAY,
                e,
            )
            time.sleep(_NETWORK_RETRY_DELAY)
    raise RuntimeError("unreachable")  # для mypy: цикл всегда вернёт/кинет


def add_to_wishlist(appid: int, access_token: str) -> Classification:
    """Один appid → добавление в вишлист; логирует wishlist_count при успехе."""
    status, eresult, body = _call("AddToWishlist", appid, access_token)
    classification = _classify(status, eresult)
    if classification == "added":
        log.info(
            "Wishlist: добавлено appid=%d (wishlist_count=%s)",
            appid,
            body.get("response", {}).get("wishlist_count"),
        )
    return classification


# Экспоненциальный backoff на rate-limit. Индекс = streak-1, капается на
# последнем элементе. Живая мера 2026-07-18: 40 добавлений подряд без пауз —
# ноль троттла (~2/сек) — устойчивый предел за тысячи adds НЕ измерен (не
# долбили ради IP soft-ban). Поэтому governor адаптивный, не хардкод: идём
# быстро, отступаем ТОЛЬКО когда Steam реально сигналит rate_limit.
_BACKOFF_SCHEDULE: tuple[float, ...] = (60.0, 120.0, 240.0, 300.0)
# 5-й подряд rate_limit — стена; долбить дальше опасно (soft-ban ~6ч,
# продлевается при долбёжке) — отличие от app/free_games/licenses.py, которая
# ретраит RateLimitExceeded бесконечно (там единственная стена — license-cap).
_WALL_STREAK = 5


def add_pending(
    access_token: str,
    appids: list[int],
    *,
    interval: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> AddResult:
    """Добавляет appids по одному (batch-эндпоинта нет).

    Rate-limit (429/eresult=84) ретраит ТОТ ЖЕ appid с растущим backoff;
    streak подряд идущих rate-limit сбрасывается любым иным исходом. 5 подряд
    → hit_wall=True, стоп, оставшийся pending не трогаем. auth_fail (401) —
    немедленный стоп (caller решает, обновлять ли токен). Сетевое исключение
    на appid (уже пережившее собственный ретрай _call, см. выше) → error,
    переходим к следующему (здесь повторно не ретраим).
    """
    result = AddResult()
    streak = 0
    i = 0
    while i < len(appids):
        appid = appids[i]
        try:
            classification = add_to_wishlist(appid, access_token)
        except Exception as e:  # noqa: BLE001 — любой сетевой сбой → error appid
            log.warning("Wishlist: сетевой сбой на appid=%d: %s", appid, e)
            result.error.append(appid)
            streak = 0
            i += 1
            continue

        if classification == "added":
            result.added.append(appid)
            streak = 0
            i += 1
            sleep(interval)
        elif classification == "refused":
            result.refused.append(appid)
            streak = 0
            i += 1
            sleep(interval)
        elif classification == "auth_fail":
            result.auth_fail = True
            break
        else:  # "rate_limit"
            streak += 1
            if streak >= _WALL_STREAK:
                result.hit_wall = True
                log.warning(
                    "Wishlist: %d подряд rate-limit — стена. Добавлено: %d",
                    streak,
                    len(result.added),
                )
                break
            delay = _BACKOFF_SCHEDULE[
                min(streak - 1, len(_BACKOFF_SCHEDULE) - 1)
            ]
            log.warning(
                "Wishlist: rate-limit (streak %d/%d) — жду %.0fс",
                streak,
                _WALL_STREAK,
                delay,
            )
            sleep(delay)
            # retry ТОТ ЖЕ appid — i не увеличиваем
    return result
