"""Разбор инвентаря Steam Community (appid 753, context 6) в предметы (B-16).

Эндпоинт снят живьём 19.10.2026: GET /inventory/{id64}/753/6?l=english&count=2000
работает с одной кукой steamLoginSecure. assets — что лежит (assetid, amount),
descriptions — что это (marketable, теги, owner_actions с GetGooValue).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_MAX_PAGES = 50  # защита от бесконечной пагинации
_GOO_RE = re.compile(
    r"GetGooValue\(\s*'%contextid%',\s*'%assetid%',\s*(\d+),\s*(\d+),\s*(\d+)"
)
# Временный запрет (снят живьём 22.10.2026): «Tradable After: 26 Oct @ 12:00am»
_LOCK_RE = re.compile(r"\b(?:tradable|marketable)\b[^:]*\bafter\b", re.I)


@dataclass(frozen=True)
class GooParams:
    """Параметры ajaxgetgoovalueforitemtype / ajaxgrindintogoo из owner_actions."""

    appid: int
    item_type: int
    border: int


@dataclass(frozen=True)
class Item:
    assetid: str
    amount: int
    market_hash_name: str
    marketable: bool
    # item_class_N: 2 карточка, 3 фон, 4 смайлик, 5 бустер-пак…
    item_class: str | None
    game_appid: int | None  # тег Game: app_N
    card_border: int | None  # тег cardborder_N: 0 обычная, 1 металлическая
    goo: GooParams | None
    # Недавно получен: продать нельзя до даты из owner_descriptions
    trade_locked: bool = False


def _tag(desc: dict[str, Any], category: str) -> str | None:
    for t in desc.get("tags", []) or []:
        if t.get("category") == category:
            value = t.get("internal_name")
            return str(value) if value is not None else None
    return None


def _suffix_int(value: str | None, prefix: str) -> int | None:
    if value and value.startswith(prefix):
        tail = value[len(prefix) :]
        if tail.isdigit():
            return int(tail)
    return None


def _goo(desc: dict[str, Any]) -> GooParams | None:
    for action in desc.get("owner_actions", []) or []:
        m = _GOO_RE.search(action.get("link", ""))
        if m:
            appid, item_type, border = (int(g) for g in m.groups())
            return GooParams(appid, item_type, border)
    return None


def _trade_locked(desc: dict[str, Any]) -> bool:
    return any(
        _LOCK_RE.search(str(note.get("value", "")))
        for note in desc.get("owner_descriptions", []) or []
    )


def parse_inventory(body: dict[str, Any]) -> list[Item]:
    """assets + descriptions одной страницы → предметы (без описания — пропуск)."""
    descs = {
        (d["classid"], d["instanceid"]): d
        for d in body.get("descriptions", []) or []
    }
    result: list[Item] = []
    for a in body.get("assets", []) or []:
        d = descs.get((a["classid"], a["instanceid"]))
        if d is None:
            continue
        result.append(
            Item(
                assetid=str(a["assetid"]),
                amount=int(a.get("amount", 1)),
                market_hash_name=d["market_hash_name"],
                marketable=bool(d.get("marketable")),
                item_class=_tag(d, "item_class"),
                game_appid=_suffix_int(_tag(d, "Game"), "app_"),
                card_border=_suffix_int(_tag(d, "cardborder"), "cardborder_"),
                goo=_goo(d),
                trade_locked=_trade_locked(d),
            )
        )
    return result


def fetch_inventory(
    steamid64: str, get_json: Callable[[str], dict[str, Any]]
) -> list[Item]:
    """Весь инвентарь с пагинацией по start_assetid. get_json — транспорт."""
    base = (
        f"https://steamcommunity.com/inventory/{steamid64}/753/6"
        "?l=english&count=2000"
    )
    result: list[Item] = []
    url = base
    for _ in range(_MAX_PAGES):
        body = get_json(url)
        result.extend(parse_inventory(body))
        last = body.get("last_assetid")
        if not body.get("more_items") or not last:
            break
        url = f"{base}&start_assetid={last}"
    return result
