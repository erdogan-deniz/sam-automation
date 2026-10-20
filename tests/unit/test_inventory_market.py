"""Тесты app/inventory/market.py: orderbook, самоцветы, sellitem, grind (B-16).

Формы ответов — из живых проб 19.10.2026.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.inventory import market
from app.inventory.items import GooParams
from app.inventory.plan import Quote


class FakeHttp:
    def __init__(self, *, get: Any = None, post: Any = None) -> None:
        self._get = get
        self._post = post
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict[str, str], str]] = []

    def get_json(self, url: str) -> dict[str, Any]:
        self.gets.append(url)
        if isinstance(self._get, Exception):
            raise self._get
        return self._get  # type: ignore[no-any-return]

    def post_form(
        self, url: str, form: dict[str, str], referer: str
    ) -> tuple[int, dict[str, Any] | None]:
        self.posts.append((url, form, referer))
        return self._post  # type: ignore[no-any-return]


_BOOK = {
    "data": {
        "success": True,
        "data": {
            "amtMaxBuyOrder": 384,
            "amtMinSellOrder": 638,
            "eCurrency": 5,
            "cBuyOrders": 9,
            "cSellOrders": 2,
        },
    }
}


def test_get_quote_reads_orderbook_by_market_hash_name() -> None:
    http = FakeHttp(get=_BOOK)
    q = market.get_quote(http, "241720-Pirate Bay Wallpaper")
    assert q == Quote(max_buy=384, min_sell=638, currency=5)
    url = urlparse(http.gets[0])
    assert url.path == "/market/orderbook"
    qs = parse_qs(url.query)
    assert qs["q"] == ["Load"]
    assert json.loads(qs["qp"][0]) == [753, "241720-Pirate Bay Wallpaper"]


def test_get_quote_without_buy_orders_has_none_bid() -> None:
    book = {
        "data": {
            "success": True,
            "data": {
                "amtMaxBuyOrder": None,
                "amtMinSellOrder": 252,
                "eCurrency": 5,
            },
        }
    }
    q = market.get_quote(FakeHttp(get=book), "x")
    assert q == Quote(max_buy=None, min_sell=252, currency=5)


def test_get_quote_unsuccessful_is_none() -> None:
    assert (
        market.get_quote(FakeHttp(get={"data": {"success": False}}), "x")
        is None
    )


def test_get_quote_garbage_is_none() -> None:
    assert market.get_quote(FakeHttp(get={}), "x") is None


def test_get_goo_value_parses_string_value() -> None:
    http = FakeHttp(get={"success": 1, "goo_value": "80"})
    assert market.get_goo_value(http, GooParams(241720, 27, 0)) == 80
    qs = parse_qs(urlparse(http.gets[0]).query)
    assert qs == {
        "appid": ["241720"],
        "item_type": ["27"],
        "border_color": ["0"],
    }


def test_get_goo_value_failure_is_none() -> None:
    assert (
        market.get_goo_value(FakeHttp(get={"success": 0}), GooParams(1, 2, 3))
        is None
    )


# --- sellitem -------------------------------------------------------------

_SELL_OK = {
    "success": True,
    "requires_confirmation": 1,
    "needs_mobile_confirmation": True,
    "needs_email_confirmation": False,
}


def test_sell_item_posts_received_amount_and_reports_pending() -> None:
    http = FakeHttp(post=(200, _SELL_OK))
    out = market.sell_item(http, "7656", assetid="111", amount=1, received=216)
    assert out == "pending_confirm"
    url, form, referer = http.posts[0]
    assert url == "https://steamcommunity.com/market/sellitem/"
    assert form == {
        "appid": "753",
        "contextid": "6",
        "assetid": "111",
        "amount": "1",
        "price": "216",
    }
    assert referer == "https://steamcommunity.com/profiles/7656/inventory"


def test_sell_item_without_confirmation_is_listed() -> None:
    http = FakeHttp(post=(200, {"success": True}))
    assert (
        market.sell_item(http, "7656", assetid="1", amount=1, received=100)
        == "listed"
    )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, None, "rate_limit"),
        (401, None, "auth_fail"),
        (403, None, "auth_fail"),
        (200, {"success": False, "message": "no"}, "refused"),
        (200, None, "refused"),
        (500, None, "error"),
    ],
)
def test_sell_item_classification(status, body, expected) -> None:
    http = FakeHttp(post=(status, body))
    assert (
        market.sell_item(http, "7656", assetid="1", amount=1, received=100)
        == expected
    )


# --- grind ----------------------------------------------------------------

_GRIND_OK = {
    "success": 1,
    "strHTML": "<div>Success! You have 10 more Gems, for a total of 982.</div>",
    "goo_value_received ": "10",  # ключ с пробелом на конце — как в живом ответе
    "goo_value_total": "982",
}


def test_grind_item_posts_expected_value_and_parses_received() -> None:
    http = FakeHttp(post=(200, _GRIND_OK))
    res = market.grind_item(
        http, "7656", assetid="9", goo=GooParams(292570, 10, 0), expected=10
    )
    assert res == ("ok", 10)
    url, form, _ref = http.posts[0]
    assert url == "https://steamcommunity.com/profiles/7656/ajaxgrindintogoo/"
    assert form == {
        "appid": "292570",
        "assetid": "9",
        "contextid": "6",
        "goo_value_expected": "10",
    }


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, None, "rate_limit"),
        (401, None, "auth_fail"),
        (200, {"success": 0}, "refused"),
        (200, None, "refused"),
        (502, None, "error"),
    ],
)
def test_grind_item_classification(status, body, expected) -> None:
    http = FakeHttp(post=(status, body))
    res = market.grind_item(
        http, "7656", assetid="9", goo=GooParams(1, 2, 3), expected=10
    )
    assert res == (expected, 0)


def test_sell_item_pending_limit_is_its_own_outcome() -> None:
    http = FakeHttp(
        post=(
            200,
            {
                "success": False,
                "message": "You have too many listings pending confirmation. "
                "Please confirm or cancel some before attempting to list more.",
            },
        )
    )
    assert (
        market.sell_item(http, "7656", assetid="1", amount=1, received=100)
        == "pending_limit"
    )


def test_sell_item_logs_steam_refusal_message(caplog) -> None:
    http = FakeHttp(post=(200, {"success": False, "message": "Nope, no."}))
    with caplog.at_level("WARNING", logger="sam_automation"):
        market.sell_item(http, "7656", assetid="42", amount=1, received=100)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "42" in text and "Nope, no." in text
