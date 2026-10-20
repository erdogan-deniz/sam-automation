"""Тесты app/inventory/plan.py и badges.py: правила выбора (B-16)."""

from __future__ import annotations

from typing import Any

import pytest

from app.inventory import badges, fees, items, plan

M = fees.min_fee(5)
SACK_BID = 5508  # живая лучшая заявка на мешок самоцветов 19.10.2026


def _item(**kw: Any) -> items.Item:
    base: dict[str, Any] = {
        "assetid": "1",
        "amount": 1,
        "market_hash_name": "241720-Pirate Bay Wallpaper",
        "marketable": True,
        "item_class": "item_class_3",
        "game_appid": 241720,
        "card_border": None,
        "goo": items.GooParams(241720, 27, 0),
    }
    base.update(kw)
    return items.Item(**base)


def _decide(it: items.Item, **kw: Any) -> plan.Decision:
    args: dict[str, Any] = {
        "quote": plan.Quote(max_buy=None, min_sell=None, currency=5),
        "goo_value": 80,
        "sack_bid": SACK_BID,
        "sack_currency": 5,
        "badge_levels": {},
        "m": M,
    }
    args.update(kw)
    return plan.decide(it, **args)


def test_not_marketable_is_skipped() -> None:
    d = _decide(_item(marketable=False))
    assert d.action == "skip"


def test_booster_pack_is_never_touched() -> None:
    d = _decide(
        _item(item_class="item_class_5"),
        quote=plan.Quote(max_buy=9999, min_sell=10000, currency=5),
    )
    assert d.action == "skip"
    assert "бустер" in d.reason


def test_best_bid_wins_over_gems_sells_at_bid() -> None:
    # заявка 5671 на руки 4932, самоцветы на 10 шт. = 55 коп.
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=5671, min_sell=8273, currency=5),
        goo_value=10,
    )
    assert d.action == "sell_bid"
    assert d.received == 4932


def test_gems_worth_more_than_bid_grinds() -> None:
    # заявка 384 на руки 216, 80 самоцветов = 440 коп.
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=384, min_sell=638, currency=5),
        goo_value=80,
    )
    assert d.action == "grind"
    assert d.gems == 80


def test_no_bids_sells_at_lowest_ask() -> None:
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=None, min_sell=252, currency=5),
        goo_value=10,
    )
    assert d.action == "sell_ask"
    assert d.received == 84  # 252 покупателю -> 84 на руки


def test_no_bids_and_gems_worth_more_than_ask_grinds() -> None:
    # Правило 20.10.2026: без заявок цена продажи тоже против самоцветов.
    # цена 252 -> 84 на руки, 80 самоцветов = 440
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=None, min_sell=252, currency=5),
        goo_value=80,
    )
    assert d.action == "grind"
    assert d.gems == 80


def test_no_bids_ask_worth_more_than_gems_sells_at_ask() -> None:
    # цена 638 -> 470 на руки, 80 самоцветов = 440
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=None, min_sell=638, currency=5),
        goo_value=80,
    )
    assert d.action == "sell_ask"
    assert d.received == 470


def test_bid_is_taken_even_when_lowest_ask_is_higher() -> None:
    # Заявка есть — продаём по ней, цену продажи не смотрим.
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=5671, min_sell=8273, currency=5),
        goo_value=0,
    )
    assert d.action == "sell_bid"
    assert d.received == 4932


def test_no_bids_and_no_asks_is_skipped() -> None:
    d = _decide(_item())
    assert d.action == "skip"


def test_bid_too_small_to_cover_fees_falls_back_to_ask() -> None:
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=100, min_sell=252, currency=5),
        goo_value=0,
    )
    assert d.action == "sell_ask"


def test_item_without_goo_never_grinds() -> None:
    d = _decide(
        _item(goo=None),
        quote=plan.Quote(max_buy=100000, min_sell=100500, currency=5),
        goo_value=None,
    )
    assert d.action == "sell_bid"


def test_stack_is_never_ground() -> None:
    d = _decide(
        _item(amount=3),
        quote=plan.Quote(max_buy=384, min_sell=638, currency=5),
        goo_value=80,
    )
    assert d.action == "sell_bid"


def test_missing_sack_price_does_not_block_selling() -> None:
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=5671, min_sell=8273, currency=5),
        sack_bid=None,
    )
    assert d.action == "sell_bid"


def test_currency_mismatch_is_skipped() -> None:
    d = _decide(
        _item(),
        quote=plan.Quote(max_buy=5671, min_sell=8273, currency=1),
    )
    assert d.action == "skip"
    assert "валют" in d.reason


def test_no_market_data_is_skipped() -> None:
    assert _decide(_item(), quote=None).action == "skip"


# --- карточки -------------------------------------------------------------


def _card(border: int = 0, appid: int = 440) -> items.Item:
    return _item(
        item_class="item_class_2",
        game_appid=appid,
        card_border=border,
        market_hash_name=f"{appid}-Card",
    )


_BID = plan.Quote(max_buy=5671, min_sell=8273, currency=5)


def test_card_of_unfinished_badge_is_skipped() -> None:
    d = _decide(_card(), quote=_BID, badge_levels={(440, 0): 4})
    assert d.action == "skip"
    assert "значок" in d.reason


def test_card_without_badge_data_is_skipped() -> None:
    assert _decide(_card(), quote=_BID, badge_levels={}).action == "skip"


def test_card_of_maxed_regular_badge_is_sold() -> None:
    d = _decide(_card(), quote=_BID, badge_levels={(440, 0): 5})
    assert d.action == "sell_bid"


def test_foil_card_needs_foil_badge_level_one() -> None:
    d_no = _decide(_card(border=1), quote=_BID, badge_levels={(440, 0): 5})
    assert d_no.action == "skip"
    d_yes = _decide(_card(border=1), quote=_BID, badge_levels={(440, 1): 1})
    assert d_yes.action == "sell_bid"


def test_card_with_unknown_border_is_skipped() -> None:
    d = _decide(
        _item(item_class="item_class_2", game_appid=440, card_border=None),
        quote=_BID,
        badge_levels={(440, 0): 5},
    )
    assert d.action == "skip"


# --- значки ---------------------------------------------------------------


def test_load_badge_levels_keeps_best_level_per_app_and_border() -> None:
    got = badges.badge_levels(
        [
            {"appid": 440, "level": 3, "border_color": 0},
            {"appid": 440, "level": 5, "border_color": 0},
            {"appid": 440, "level": 1, "border_color": 1},
            {"badgeid": 1, "level": 9},  # без appid (системный значок)
        ]
    )
    assert got == {(440, 0): 5, (440, 1): 1}


@pytest.mark.parametrize(
    ("border", "level", "maxed"),
    [(0, 4, False), (0, 5, True), (0, 40, True), (1, 0, False), (1, 1, True)],
)
def test_is_maxed(border, level, maxed) -> None:
    assert badges.is_maxed(border, level) is maxed


def test_fetch_badges_calls_getbadges_and_parses() -> None:
    seen: list[str] = []

    def get_json(url: str) -> dict[str, Any]:
        seen.append(url)
        return {
            "response": {
                "badges": [{"appid": 7, "level": 5, "border_color": 0}]
            }
        }

    got = badges.fetch_badge_levels("KEY", "7656", get_json)
    assert got == {(7, 0): 5}
    assert "IPlayerService/GetBadges/v1" in seen[0]
    assert "steamid=7656" in seen[0]


# --- skip_reason: что отсекается до запросов к маркету --------------------


def test_skip_reason_none_for_plain_marketable_item() -> None:
    assert plan.skip_reason(_item(), {}) is None


def test_skip_reason_for_non_marketable_booster_and_unfinished_card() -> None:
    assert plan.skip_reason(_item(marketable=False), {}) is not None
    assert plan.skip_reason(_item(item_class="item_class_5"), {}) is not None
    assert plan.skip_reason(_card(), {(440, 0): 2}) is not None
    assert plan.skip_reason(_card(), {(440, 0): 5}) is None
