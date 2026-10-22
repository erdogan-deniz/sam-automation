"""Тесты app/inventory/items.py: разбор инвентаря 753/6 (B-16)."""

from __future__ import annotations

from typing import Any

from app.inventory import items


def _desc(
    classid: str,
    *,
    name: str,
    marketable: int = 1,
    item_class: str = "item_class_3",
    game_app: int | None = 241720,
    goo: tuple[int, int, int] | None = (241720, 27, 0),
    cardborder: str | None = None,
    owner_note: str | None = None,
) -> dict[str, Any]:
    tags = [{"category": "item_class", "internal_name": item_class}]
    if game_app is not None:
        tags.append({"category": "Game", "internal_name": f"app_{game_app}"})
    if cardborder is not None:
        tags.append({"category": "cardborder", "internal_name": cardborder})
    owner_actions = []
    if goo is not None:
        a, t, b = goo
        owner_actions.append(
            {
                "link": f"javascript:GetGooValue( '%contextid%', '%assetid%', "
                f"{a}, {t}, {b} )",
                "name": "Turn into Gems...",
            }
        )
    desc: dict[str, Any] = {
        "classid": classid,
        "instanceid": "0",
        "market_hash_name": name,
        "marketable": marketable,
        "tags": tags,
        "owner_actions": owner_actions,
    }
    if owner_note is not None:
        desc["owner_descriptions"] = [{"type": "html", "value": owner_note}]
    return desc


def _asset(assetid: str, classid: str, amount: str = "1") -> dict[str, Any]:
    return {
        "assetid": assetid,
        "classid": classid,
        "instanceid": "0",
        "amount": amount,
    }


def test_parses_marketable_background_with_goo_params() -> None:
    body = {
        "assets": [_asset("111", "1")],
        "descriptions": [_desc("1", name="241720-Pirate Bay Wallpaper")],
    }
    [it] = items.parse_inventory(body)
    assert it.assetid == "111"
    assert it.amount == 1
    assert it.market_hash_name == "241720-Pirate Bay Wallpaper"
    assert it.marketable is True
    assert it.item_class == "item_class_3"
    assert it.game_appid == 241720
    assert it.goo == items.GooParams(appid=241720, item_type=27, border=0)


def test_item_without_turn_into_gems_has_no_goo() -> None:
    body = {
        "assets": [_asset("1", "1")],
        "descriptions": [_desc("1", name="x", goo=None)],
    }
    assert items.parse_inventory(body)[0].goo is None


def test_non_marketable_flag_is_kept() -> None:
    body = {
        "assets": [_asset("1", "1")],
        "descriptions": [_desc("1", name="753-Gems", marketable=0)],
    }
    assert items.parse_inventory(body)[0].marketable is False


def test_temporary_trade_lock_is_detected() -> None:
    # Живьём 22.10.2026: недавно полученный фон — marketable 0 и
    # «Tradable After: 26 Oct @ 12:00am» в owner_descriptions.
    body = {
        "assets": [_asset("1", "1"), _asset("2", "2")],
        "descriptions": [
            _desc(
                "1",
                name="1280260-Juno Gun",
                marketable=0,
                owner_note="Tradable After: 26 Oct @ 12:00am",
            ),
            _desc("2", name="442810-Welcome back", marketable=0),
        ],
    }
    locked, forever = items.parse_inventory(body)
    assert locked.trade_locked is True
    assert forever.trade_locked is False


def test_other_owner_note_is_not_a_lock() -> None:
    body = {
        "assets": [_asset("1", "1")],
        "descriptions": [
            _desc(
                "1",
                name="x",
                marketable=0,
                owner_note="Received from claiming a free sale reward.",
            )
        ],
    }
    assert items.parse_inventory(body)[0].trade_locked is False


def test_card_border_tag_is_parsed() -> None:
    body = {
        "assets": [_asset("1", "1")],
        "descriptions": [
            _desc(
                "1",
                name="440-Card",
                item_class="item_class_2",
                cardborder="cardborder_1",
            )
        ],
    }
    assert items.parse_inventory(body)[0].card_border == 1


def test_stack_amount_is_kept() -> None:
    body = {
        "assets": [_asset("1", "1", amount="6")],
        "descriptions": [_desc("1", name="x")],
    }
    assert items.parse_inventory(body)[0].amount == 6


def test_asset_without_description_is_skipped() -> None:
    body = {"assets": [_asset("1", "404")], "descriptions": []}
    assert items.parse_inventory(body) == []


def test_empty_inventory() -> None:
    assert items.parse_inventory({}) == []


def test_fetch_inventory_follows_pagination() -> None:
    pages = [
        {
            "assets": [_asset("1", "1")],
            "descriptions": [_desc("1", name="a")],
            "more_items": 1,
            "last_assetid": "1",
        },
        {
            "assets": [_asset("2", "2")],
            "descriptions": [_desc("2", name="b")],
        },
    ]
    urls: list[str] = []

    def get_json(url: str) -> dict[str, Any]:
        urls.append(url)
        return pages[len(urls) - 1]

    got = items.fetch_inventory("7656", get_json)
    assert [i.assetid for i in got] == ["1", "2"]
    assert "start_assetid" not in urls[0]
    assert "start_assetid=1" in urls[1]
    assert "/inventory/7656/753/6" in urls[0]
