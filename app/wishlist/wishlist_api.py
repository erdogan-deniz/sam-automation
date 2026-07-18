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

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
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


def _call(
    action: str, appid: int, access_token: str
) -> tuple[int, str | None, dict[str, Any]]:
    """POST IWishlistService/<action>/v1/. Возвращает (http_status, x-eresult, body).

    Сетевые исключения (URLError/OSError/HTTPException — НЕ HTTPError, тот уже
    несёт валидный http_status) пробрасываются наверх — вызывающий
    add_pending() ловит их как error-исход для конкретного appid.
    """
    url = (
        f"{BASE_URL}/IWishlistService/{action}/v1/?access_token={access_token}"
    )
    data = urllib.parse.urlencode({"appid": appid}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": _FORM_CONTENT_TYPE}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            eresult = resp.headers.get("x-eresult")
            try:
                body: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = {}
            return resp.status, eresult, body
    except urllib.error.HTTPError as e:
        eresult = e.headers.get("x-eresult") if e.headers else None
        return e.code, eresult, {}


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
