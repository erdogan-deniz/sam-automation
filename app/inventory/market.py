"""Запросы к маркету и самоцветам Steam Community (B-16).

Все эндпоинты сняты живьём 19.10.2026 (см. docs/superpowers/specs/
2026-10-19-inventory-sale-design.md):

  * market/orderbook?q=Load&qp=[753,"<market_hash_name>"] — лучшая заявка и
    цена продажи в валюте кошелька. Старые market/listings и priceoverview из
    Python отвечали 429 вразнобой и в дизайн не вошли.
  * auction/ajaxgetgoovalueforitemtype — самоцветов за предмет (строка).
  * market/sellitem/ — лот; price = сумма на руки продавцу, подтверждение в
    мобильном Steam Guard (needs_mobile_confirmation).
  * profiles/{id}/ajaxgrindintogoo/ — разбор; в ответе ключ
    "goo_value_received " записан с пробелом на конце.

Транспорт (cookie, sessionid, ретраи чтения) — за протоколом Http, поэтому
здесь только форма запросов и классификация ответов.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Literal, Protocol

from app.exceptions import SAMError
from app.inventory.items import GooParams
from app.inventory.plan import Quote

log = logging.getLogger("sam_automation")

_COMMUNITY = "https://steamcommunity.com"

SellOutcome = Literal[
    "listed",
    "pending_confirm",
    "pending_limit",
    "refused",
    "rate_limit",
    "auth_fail",
    "error",
]
GrindOutcome = Literal["ok", "refused", "rate_limit", "auth_fail", "error"]


class RateLimited(SAMError):
    """Steam отвечает 429 и после ретраев транспорта."""


class AuthExpired(SAMError):
    """Сессия истекла или нет доступа (401/403)."""


class Http(Protocol):
    def get_json(self, url: str) -> dict[str, Any]: ...

    def post_form(
        self, url: str, form: dict[str, str], referer: str
    ) -> tuple[int, dict[str, Any] | None]:
        """POST формы (sessionid добавляет транспорт). (HTTP-статус, JSON|None)."""
        ...


def get_quote(http: Http, market_hash_name: str) -> Quote | None:
    """Стакан предмета; None — ответ непригоден (не успех, нет данных)."""
    qp = json.dumps([753, market_hash_name])
    url = f"{_COMMUNITY}/market/orderbook?q=Load&qp={urllib.parse.quote(qp)}"
    body = http.get_json(url)
    inner = (body.get("data") or {}) if isinstance(body, dict) else {}
    if not inner.get("success"):
        return None
    data = inner.get("data") or {}
    if "eCurrency" not in data:
        return None
    return Quote(
        max_buy=data.get("amtMaxBuyOrder"),
        min_sell=data.get("amtMinSellOrder"),
        currency=int(data["eCurrency"]),
    )


def get_goo_value(http: Http, goo: GooParams) -> int | None:
    qs = urllib.parse.urlencode(
        {
            "appid": goo.appid,
            "item_type": goo.item_type,
            "border_color": goo.border,
        }
    )
    body = http.get_json(
        f"{_COMMUNITY}/auction/ajaxgetgoovalueforitemtype/?{qs}"
    )
    if body.get("success") != 1:
        return None
    try:
        return int(body["goo_value"])
    except (KeyError, ValueError, TypeError):
        return None


def _status_outcome(status: int) -> Literal["rate_limit", "auth_fail", "error"]:
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "auth_fail"
    return "error"


def sell_item(
    http: Http, steamid64: str, *, assetid: str, amount: int, received: int
) -> SellOutcome:
    """Выставляет лот. received — сумма на руки в копейках."""
    status, body = http.post_form(
        f"{_COMMUNITY}/market/sellitem/",
        {
            "appid": "753",
            "contextid": "6",
            "assetid": assetid,
            "amount": str(amount),
            "price": str(received),
        },
        f"{_COMMUNITY}/profiles/{steamid64}/inventory",
    )
    if status != 200:
        return _status_outcome(status)
    if not body or not body.get("success"):
        message = str((body or {}).get("message", ""))
        log.warning(
            "Steam отказал в лоте %s: %s", assetid, message or "без текста"
        )
        # Потолок неподтверждённых лотов (снят живьём 19.10.2026: 250): это не
        # отказ по предмету, а сигнал «подтвердите лоты и запустите снова».
        if "pending confirmation" in message.lower():
            return "pending_limit"
        return "refused"
    if body.get("requires_confirmation"):
        return "pending_confirm"
    return "listed"


def grind_item(
    http: Http,
    steamid64: str,
    *,
    assetid: str,
    goo: GooParams,
    expected: int,
) -> tuple[GrindOutcome, int]:
    """Разбирает предмет на самоцветы. Возвращает (исход, получено самоцветов)."""
    status, body = http.post_form(
        f"{_COMMUNITY}/profiles/{steamid64}/ajaxgrindintogoo/",
        {
            "appid": str(goo.appid),
            "assetid": assetid,
            "contextid": "6",
            "goo_value_expected": str(expected),
        },
        f"{_COMMUNITY}/profiles/{steamid64}/inventory",
    )
    if status != 200:
        return _status_outcome(status), 0
    if not body or body.get("success") != 1:
        return "refused", 0
    received = 0
    for key, value in body.items():
        if key.strip() == "goo_value_received":
            try:
                received = int(value)
            except (ValueError, TypeError):
                received = 0
    return "ok", received
