"""Правила выбора для предмета инвентаря: продать, разобрать или пропустить (B-16).

Решения владельца 18-19.10.2026 (см. docs/superpowers/specs/
2026-10-19-inventory-sale-design.md):
  * карточки — только когда значок игры собран до максимума;
  * бустер-паки не трогаем никогда;
  * есть заявка: на руки по заявке против самоцветов × заявка на мешок / 1000,
    самоцветы дороже — разбираем, иначе продаём по заявке;
  * заявок нет — выставляем по самой низкой цене продажи, пусть висит;
  * при сомнении (нет данных, другая валюта) предмет пропускается.
Суммы в минимальных единицах валюты, целые.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.inventory import badges, fees
from app.inventory.items import Item

Action = Literal["sell_bid", "sell_ask", "grind", "skip"]

_CARD = "item_class_2"
_BOOSTER = "item_class_5"
_GEMS_PER_SACK = 1000


@dataclass(frozen=True)
class Quote:
    """Срез стакана: лучшая заявка и самая низкая цена (покупательские, gross)."""

    max_buy: int | None
    min_sell: int | None
    currency: int


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str = ""
    received: int = 0  # на руки за штуку (sell_*)
    gems: int = 0  # самоцветов за штуку (grind)


def _skip(reason: str) -> Decision:
    return Decision("skip", reason=reason)


def skip_reason(
    item: Item, badge_levels: dict[tuple[int, int], int]
) -> str | None:
    """Причина пропуска, известная без запросов к маркету; None — кандидат."""
    if not item.marketable:
        return "не продаётся на маркете"
    if item.item_class == _BOOSTER:
        return "бустер-пак не трогаем"
    if item.item_class == _CARD:
        if item.game_appid is None or item.card_border is None:
            return "карточка без игры или рамки"
        level = badge_levels.get((item.game_appid, item.card_border))
        if level is None:
            return "нет данных о значке игры"
        if not badges.is_maxed(item.card_border, level):
            return "значок игры ещё не собран"
    return None


def decide(
    item: Item,
    *,
    quote: Quote | None,
    goo_value: int | None,
    sack_bid: int | None,
    sack_currency: int,
    badge_levels: dict[tuple[int, int], int],
    m: int,
) -> Decision:
    reason = skip_reason(item, badge_levels)
    if reason is not None:
        return _skip(reason)
    if quote is None:
        return _skip("нет данных рынка")
    if quote.currency != sack_currency:
        return _skip("валюта рынка не совпала с валютой кошелька")

    if quote.max_buy is not None:
        net = fees.received_from_buyer(quote.max_buy, m)
        if net > 0:
            can_grind = (
                item.goo is not None
                and item.amount == 1
                and goo_value is not None
                and sack_bid is not None
            )
            if can_grind:
                assert goo_value is not None and sack_bid is not None
                if goo_value * sack_bid // _GEMS_PER_SACK > net:
                    return Decision("grind", gems=goo_value)
            return Decision("sell_bid", received=net)

    if quote.min_sell is not None:
        net = fees.received_from_buyer(quote.min_sell, m)
        if net > 0:
            return Decision("sell_ask", received=net)
    return _skip("нет заявок и цен продажи")
