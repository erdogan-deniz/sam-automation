"""Тесты app/inventory/run.py: план, выставление, разбор, точка входа (B-16)."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.inventory.run as inv_run
import app.inventory.state as st
from app.inventory import items
from app.inventory.items import GooParams, Item
from app.inventory.market import AuthExpired
from app.inventory.plan import Decision, Quote

SACK = "753-Sack of Gems"
BG = "241720-Pirate Bay Wallpaper"
EMO = "2633890-:OS3_EM_3:"
CHEAP = "292570-Speakers"


def _item(assetid: str, name: str, **kw: Any) -> Item:
    base: dict[str, Any] = {
        "assetid": assetid,
        "amount": 1,
        "market_hash_name": name,
        "marketable": True,
        "item_class": "item_class_3",
        "game_appid": 1,
        "card_border": None,
        "goo": GooParams(1, 27, 0),
    }
    base.update(kw)
    return Item(**base)


def _book(max_buy: int | None, min_sell: int | None, cur: int = 5) -> dict:
    return {
        "data": {
            "success": True,
            "data": {
                "amtMaxBuyOrder": max_buy,
                "amtMinSellOrder": min_sell,
                "eCurrency": cur,
            },
        }
    }


class FakeHttp:
    """Маршрутизирует GET по URL, записывает POST."""

    def __init__(
        self,
        books: dict[str, dict],
        goo: dict[int, int] | None = None,
        post: Any = (200, {"success": True, "requires_confirmation": 1}),
    ) -> None:
        self.books = books
        self.goo = goo or {}
        self.post = post
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict[str, str]]] = []

    def get_json(self, url: str) -> dict[str, Any]:
        self.gets.append(url)
        if "/market/orderbook" in url:
            qp = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["qp"]
            return self.books[json.loads(qp[0])[1]]
        if "ajaxgetgoovalueforitemtype" in url:
            appid = int(
                urllib.parse.parse_qs(urllib.parse.urlparse(url).query)[
                    "appid"
                ][0]
            )
            return {"success": 1, "goo_value": str(self.goo.get(appid, 10))}
        raise AssertionError(f"неожиданный GET {url}")

    def post_form(
        self, url: str, form: dict[str, str], referer: str
    ) -> tuple[int, Any]:
        self.posts.append((url, form))
        post = self.post
        if isinstance(post, list):
            return post.pop(0)  # type: ignore[no-any-return]
        return post  # type: ignore[no-any-return]

    def ensure_session(self, steamid64: str) -> None:
        pass


@pytest.fixture(autouse=True)
def _state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(st, "LISTED_FILE", tmp_path / "listed.txt")
    monkeypatch.setattr(st, "PENDING_FILE", tmp_path / "pending.txt")
    monkeypatch.setattr(st, "GROUND_FILE", tmp_path / "ground.txt")
    monkeypatch.setattr(st, "REFUSED_FILE", tmp_path / "refused.txt")


# --- build_plan -----------------------------------------------------------


def test_build_plan_queries_market_only_for_candidates() -> None:
    http = FakeHttp({BG: _book(None, 252)})
    inv = [
        _item("1", BG),
        _item("2", "753-Gems", marketable=False),
        _item("3", "454460-Booster", item_class="item_class_5"),
    ]
    rows = inv_run.build_plan(
        http,
        inv,
        badge_levels={},
        sack_quote=Quote(5508, 5590, 5),
        m=84,
        pause=0.0,
        sleep=lambda s: None,
    )
    assert [r.decision.action for r in rows] == ["sell_ask", "skip", "skip"]
    orderbooks = [u for u in http.gets if "/market/orderbook" in u]
    assert len(orderbooks) == 1


def test_build_plan_asks_goo_when_there_is_only_an_ask() -> None:
    # Правило 20.10.2026: без заявок цена продажи сравнивается с самоцветами.
    http = FakeHttp({BG: _book(None, 252)})
    inv_run.build_plan(
        http,
        [_item("1", BG)],
        badge_levels={},
        sack_quote=Quote(5508, 5590, 5),
        m=84,
        pause=0.0,
        sleep=lambda s: None,
    )
    assert len([u for u in http.gets if "ajaxgetgoo" in u]) == 1


def test_build_plan_does_not_ask_goo_without_any_price() -> None:
    http = FakeHttp({BG: _book(None, None)})
    inv_run.build_plan(
        http,
        [_item("1", BG)],
        badge_levels={},
        sack_quote=Quote(5508, 5590, 5),
        m=84,
        pause=0.0,
        sleep=lambda s: None,
    )
    assert not [u for u in http.gets if "ajaxgetgoo" in u]


def test_build_plan_one_orderbook_per_unique_name() -> None:
    http = FakeHttp({EMO: _book(None, 252)})
    inv_run.build_plan(
        http,
        [_item("1", EMO), _item("2", EMO)],
        badge_levels={},
        sack_quote=Quote(5508, 5590, 5),
        m=84,
        pause=0.0,
        sleep=lambda s: None,
    )
    assert len([u for u in http.gets if "/market/orderbook" in u]) == 1


def test_build_plan_grinds_when_gems_beat_bid() -> None:
    # заявка 384 -> на руки 216; 80 самоцветов * 5508 / 1000 = 440
    http = FakeHttp({BG: _book(384, 638)}, goo={1: 80})
    [row] = inv_run.build_plan(
        http,
        [_item("1", BG)],
        badge_levels={},
        sack_quote=Quote(5508, 5590, 5),
        m=84,
        pause=0.0,
        sleep=lambda s: None,
    )
    assert row.decision == Decision("grind", gems=80)


# --- sell / grind ---------------------------------------------------------


def _row(assetid: str, name: str, decision: Decision, **kw: Any) -> inv_run.Row:
    return inv_run.Row(_item(assetid, name, **kw), decision)


def test_sell_pending_confirmation_is_recorded_as_pending() -> None:
    http = FakeHttp({})
    res = inv_run.sell(
        http,
        "7656",
        [_row("111", BG, Decision("sell_bid", received=216))],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.done == 1 and res.pending == 1
    assert res.received_total == 216
    assert st.load_pending() == {111}
    assert st.load_listed() == set()
    url, form = http.posts[0]
    assert form["price"] == "216" and form["assetid"] == "111"


def test_sell_without_confirmation_is_recorded_as_listed() -> None:
    http = FakeHttp({}, post=(200, {"success": True}))
    res = inv_run.sell(
        http,
        "7656",
        [_row("5", BG, Decision("sell_ask", received=84))],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.done == 1 and res.pending == 0
    assert st.load_listed() == {5}


def test_sell_refused_is_terminal_and_error_is_retryable() -> None:
    http = FakeHttp(
        {},
        post=[(200, {"success": False}), (500, None)],
    )
    res = inv_run.sell(
        http,
        "7656",
        [
            _row("1", BG, Decision("sell_ask", received=84)),
            _row("2", EMO, Decision("sell_ask", received=84)),
        ],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.refused == 1 and res.error == 1 and res.done == 0
    assert st.load_handled() == {
        1
    }  # ошибка не записана — повтор в след. прогоне


def test_sell_stops_at_wall_after_repeated_429() -> None:
    http = FakeHttp({}, post=(429, None))
    res = inv_run.sell(
        http,
        "7656",
        [_row("1", BG, Decision("sell_ask", received=84))],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.hit_wall is True and res.done == 0


def test_sell_auth_fail_stops() -> None:
    http = FakeHttp({}, post=(401, None))
    res = inv_run.sell(
        http,
        "7656",
        [_row("1", BG, Decision("sell_ask", received=84))],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.auth_fail is True


def test_sell_stack_posts_whole_amount() -> None:
    http = FakeHttp({})
    inv_run.sell(
        http,
        "7656",
        [_row("1", BG, Decision("sell_bid", received=100), amount=4)],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert http.posts[0][1]["amount"] == "4"


def test_grind_records_ground_and_gems() -> None:
    http = FakeHttp({}, post=(200, {"success": 1, "goo_value_received ": "10"}))
    res = inv_run.grind(
        http,
        "7656",
        [
            _row(
                "9",
                CHEAP,
                Decision("grind", gems=10),
                goo=GooParams(292570, 10, 0),
            )
        ],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.done == 1 and res.gems_total == 10
    assert st.load_handled() == {9}
    assert http.posts[0][1]["goo_value_expected"] == "10"


# --- run ------------------------------------------------------------------


def _cfg() -> Any:
    return SimpleNamespace(steam_api_key="k")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Инвентарь из двух предметов + реестр вызовов отчёта."""
    inv = [
        _item("10", BG),
        _item("20", EMO),
    ]
    reports: list[dict[str, Any]] = []
    monkeypatch.setattr(inv_run.items, "fetch_inventory", lambda sid, g: inv)
    monkeypatch.setattr(
        inv_run.badges, "fetch_badge_levels", lambda k, sid, g: {}
    )
    monkeypatch.setattr(
        inv_run, "report_result", lambda **kw: reports.append(kw)
    )
    monkeypatch.setattr(inv_run, "_READ_PAUSE", 0.0)
    return {"inv": inv, "reports": reports}


def _books() -> dict[str, dict]:
    return {
        SACK: _book(5508, 5590),
        BG: _book(None, 252),
        EMO: _book(None, 252),
    }


def test_run_dry_run_posts_nothing_and_reports_dry(world) -> None:
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=False,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert http.posts == []
    assert world["reports"][-1]["status"] == "dry_run"


def test_run_sell_posts_sell_rows_only(world) -> None:
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert len(http.posts) == 2
    assert all("/market/sellitem/" in u for u, _f in http.posts)
    assert world["reports"][-1]["status"] == "ok"
    assert st.load_pending() == {10, 20}


def test_run_limit_caps_operations(world) -> None:
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=1,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert len(http.posts) == 1


def test_run_skips_already_handled_assets(world) -> None:
    st.mark_pending(10)
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert [f["assetid"] for _u, f in http.posts] == ["20"]


def test_run_grind_flag_grinds_only_grind_rows(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = _books()
    books[BG] = _book(384, 638)  # самоцветы дороже заявки
    books[EMO] = _book(None, 8273)  # цена (7195) дороже самоцветов
    http = FakeHttp(
        books,
        goo={1: 80},
        post=(200, {"success": 1, "goo_value_received ": "80"}),
    )
    inv_run.run(
        do_sell=False,
        do_grind=True,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert len(http.posts) == 1
    assert "ajaxgrindintogoo" in http.posts[0][0]
    assert st.load_handled() == {10}


def test_run_unknown_currency_aborts_without_posts(world) -> None:
    books = _books()
    books[SACK] = _book(5508, 5590, cur=1)
    http = FakeHttp(books)
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert http.posts == []
    assert world["reports"][-1]["status"] == "error"


def test_run_expired_session_reports_error(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(sid: str, g: Any) -> list[Item]:
        raise AuthExpired("HTTP 401")

    monkeypatch.setattr(inv_run.items, "fetch_inventory", boom)
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert world["reports"][-1]["status"] == "error"


def test_run_reset_clears_state_and_does_nothing_else(world) -> None:
    st.mark_listed(1)
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=False,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=True,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert st.load_handled() == set()
    assert http.gets == []
    assert world["reports"] == []


def test_run_without_web_session_reports_error(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inv_run, "get_web_cookies", lambda *a, **k: None)
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        sleep=lambda s: None,
    )
    assert world["reports"][-1]["status"] == "error"


def test_run_list_prints_plan_and_sends_no_report(world, capsys) -> None:
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=False,
        do_grind=False,
        list_only=True,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    out = capsys.readouterr().out
    assert BG in out and EMO in out
    assert world["reports"] == []
    assert http.posts == []


def test_items_module_is_used_through_module_attribute() -> None:
    # run.py обращается к items/badges через модуль — тесты подменяют их так
    assert inv_run.items is items


def test_run_list_hides_non_marketable_items(world, capsys) -> None:
    world["inv"].append(_item("30", "753-Gems", marketable=False))
    http = FakeHttp(_books())
    inv_run.run(
        do_sell=False,
        do_grind=False,
        list_only=True,
        limit=None,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    out = capsys.readouterr().out
    assert BG in out
    assert "753-Gems" not in out


def test_run_sells_bid_rows_before_ask_rows(world) -> None:
    """--limit 1 сначала проверяет лот по заявке (мгновенная продажа)."""
    books = _books()
    books[EMO] = _book(5671, 8273)  # у второго предмета есть заявка
    http = FakeHttp(books, goo={1: 10})
    inv_run.run(
        do_sell=True,
        do_grind=False,
        list_only=False,
        limit=1,
        interval=0.0,
        reset=False,
        steam_id="7656",
        cfg=_cfg(),
        http=http,
        sleep=lambda s: None,
    )
    assert [f["assetid"] for _u, f in http.posts] == ["20"]  # EMO, не BG


_CAP = {
    "success": False,
    "message": "You have too many listings pending confirmation. "
    "Please confirm or cancel some before attempting to list more.",
}


def test_sell_pending_limit_stops_without_marking_the_rest() -> None:
    http = FakeHttp(
        {},
        post=[
            (200, {"success": True, "requires_confirmation": 1}),
            (200, _CAP),
        ],
    )
    res = inv_run.sell(
        http,
        "7656",
        [
            _row("1", BG, Decision("sell_ask", received=84)),
            _row("2", EMO, Decision("sell_ask", received=84)),
            _row("3", CHEAP, Decision("sell_ask", received=84)),
        ],
        interval=0.0,
        sleep=lambda s: None,
    )
    assert res.done == 1 and res.pending == 1
    assert res.hit_wall is True and res.refused == 0
    assert len(http.posts) == 2  # третий предмет даже не пробовали
    assert st.load_handled() == {
        1
    }  # второй и третий повторятся в след. прогоне
