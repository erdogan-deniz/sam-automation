"""Распродажа инвентаря Steam: план, выставление лотов, разбор (B-16).

Порядок: инвентарь → значки → стакан мешка самоцветов (валюта кошелька и цена
самоцвета) → стакан и самоцветы по каждому кандидату → план. Без флагов —
dry-run (только подсчёт). --sell выставляет лоты, --grind разбирает на
самоцветы; оба цикла идут через wishlist_api.add_pending: тот же backoff на
429, та же стена и персист после каждого предмета.

Лот, выставленный и ждущий подтверждения в мобильном Steam Guard, — состояние
pending, а не «продано»: пока владелец не подтвердил, лота нет.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.cookies import get_web_cookies
from app.exceptions import SAMError
from app.inventory import badges, fees, items, market, plan, state
from app.inventory.http import SteamHttp
from app.inventory.items import Item
from app.inventory.plan import Decision, Quote
from app.logging_setup import SEPARATOR
from app.wishlist import wishlist_api
from app.wishlist.report import report_result

log = logging.getLogger("sam_automation")

SACK_NAME = "753-Sack of Gems"
_READ_PAUSE = 1.0  # пауза между запросами чтения к маркету (429 вразнобой)
_TITLE = "Распродажа инвентаря"
_LABEL = "Распродажа"


@dataclass
class Row:
    item: Item
    decision: Decision


@dataclass
class Result:
    done: int = 0
    pending: int = 0
    refused: int = 0
    error: int = 0
    hit_wall: bool = False
    auth_fail: bool = False
    received_total: int = 0  # копеек на руки (sell)
    gems_total: int = 0  # самоцветов (grind)


def build_plan(
    http: market.Http,
    inventory: list[Item],
    *,
    badge_levels: dict[tuple[int, int], int],
    sack_quote: Quote,
    m: int,
    pause: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Row]:
    """Решение по каждому предмету; рынок опрашивается только у кандидатов."""
    gap = _READ_PAUSE if pause is None else pause
    candidates = [
        it for it in inventory if plan.skip_reason(it, badge_levels) is None
    ]
    quotes: dict[str, Quote | None] = {}
    for it in candidates:
        name = it.market_hash_name
        if name not in quotes:
            quotes[name] = market.get_quote(http, name)
            sleep(gap)
    goo_values: dict[items.GooParams, int | None] = {}
    for it in candidates:
        quote = quotes[it.market_hash_name]
        # самоцветы нужны только при заявке: без неё разбор не рассматривается
        if (
            it.goo is not None
            and it.amount == 1
            and quote is not None
            and quote.max_buy is not None
            and it.goo not in goo_values
        ):
            goo_values[it.goo] = market.get_goo_value(http, it.goo)
            sleep(gap)
    rows: list[Row] = []
    for it in inventory:
        decision = plan.decide(
            it,
            quote=quotes.get(it.market_hash_name),
            goo_value=goo_values.get(it.goo) if it.goo else None,
            sack_bid=sack_quote.max_buy,
            sack_currency=sack_quote.currency,
            badge_levels=badge_levels,
            m=m,
        )
        rows.append(Row(it, decision))
    return rows


def _loop(
    rows: list[Row],
    op: Callable[[Row], str],
    *,
    interval: float,
    sleep: Callable[[float], None],
    persist_ok: Callable[[int, str], None],
) -> tuple[wishlist_api.AddResult, dict[int, str], dict[int, Row]]:
    by_asset = {int(r.item.assetid): r for r in rows}
    raw: dict[int, str] = {}

    def call(asset: int, _token: str) -> wishlist_api.Classification:
        outcome = op(by_asset[asset])
        raw[asset] = outcome
        if outcome in ("listed", "pending_confirm", "ok"):
            return "added"
        if outcome in ("refused", "rate_limit", "auth_fail"):
            return outcome  # type: ignore[return-value]
        raise RuntimeError(f"сбой операции: {outcome}")

    def persist(asset: int, outcome: str) -> None:
        if outcome == "added":
            persist_ok(asset, raw[asset])
        elif outcome == "refused":
            state.mark_refused(asset)

    res = wishlist_api.add_pending(
        "",
        list(by_asset),
        interval=interval,
        sleep=sleep,
        persist=persist,
        call=call,
        label=_LABEL,
    )
    return res, raw, by_asset


def sell(
    http: market.Http,
    steamid64: str,
    rows: list[Row],
    *,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    """Выставляет лоты по решению sell_bid/sell_ask."""

    def op(row: Row) -> str:
        return market.sell_item(
            http,
            steamid64,
            assetid=row.item.assetid,
            amount=row.item.amount,
            received=row.decision.received,
        )

    def persist_ok(asset: int, outcome: str) -> None:
        if outcome == "pending_confirm":
            state.mark_pending(asset)
        else:
            state.mark_listed(asset)

    res, raw, by_asset = _loop(
        rows, op, interval=interval, sleep=sleep, persist_ok=persist_ok
    )
    out = Result(
        done=len(res.added),
        pending=sum(1 for a in res.added if raw[a] == "pending_confirm"),
        refused=len(res.refused),
        error=len(res.error),
        hit_wall=res.hit_wall,
        auth_fail=res.auth_fail,
    )
    out.received_total = sum(
        by_asset[a].decision.received * by_asset[a].item.amount
        for a in res.added
    )
    return out


def grind(
    http: market.Http,
    steamid64: str,
    rows: list[Row],
    *,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    """Разбирает предметы на самоцветы по решению grind."""
    gems: dict[int, int] = {}

    def op(row: Row) -> str:
        goo = row.item.goo
        assert goo is not None
        outcome, got = market.grind_item(
            http,
            steamid64,
            assetid=row.item.assetid,
            goo=goo,
            expected=row.decision.gems,
        )
        if outcome == "ok":
            gems[int(row.item.assetid)] = got
        return outcome

    res, _raw, _by = _loop(
        rows,
        op,
        interval=interval,
        sleep=sleep,
        persist_ok=lambda asset, _o: state.mark_ground(asset),
    )
    return Result(
        done=len(res.added),
        refused=len(res.refused),
        error=len(res.error),
        hit_wall=res.hit_wall,
        auth_fail=res.auth_fail,
        gems_total=sum(gems.get(a, 0) for a in res.added),
    )


def _rub(kopecks: int) -> str:
    return f"{kopecks // 100},{kopecks % 100:02d}"


def _print_plan(rows: list[Row]) -> None:
    for r in rows:
        if not r.item.marketable:
            continue  # не продаётся на маркете: сотни строк без решения
        d = r.decision
        if d.action == "skip":
            tail = d.reason
        elif d.action == "grind":
            tail = f"{d.gems} самоцветов"
        else:
            tail = f"на руки {_rub(d.received)}"
        print(
            f"{r.item.assetid:>14}  {r.item.market_hash_name:<44} "
            f"{d.action:<9} {tail}"
        )


def _summarize(rows: list[Row]) -> None:
    by_action = Counter(r.decision.action for r in rows)
    sell_total = sum(
        r.decision.received * r.item.amount
        for r in rows
        if r.decision.action in ("sell_bid", "sell_ask")
    )
    gems_total = sum(
        r.decision.gems for r in rows if r.decision.action == "grind"
    )
    log.info(SEPARATOR)
    log.info(
        "План: продать по заявке %d, выставить по цене продажи %d "
        "(≈ %s руб на руки), разобрать %d (%d самоцветов), пропустить %d",
        by_action["sell_bid"],
        by_action["sell_ask"],
        _rub(sell_total),
        by_action["grind"],
        gems_total,
        by_action["skip"],
    )
    reasons = Counter(
        r.decision.reason for r in rows if r.decision.action == "skip"
    )
    for reason, n in reasons.most_common():
        log.info("  пропущено %d: %s", n, reason)


def run(
    *,
    do_sell: bool,
    do_grind: bool,
    list_only: bool,
    limit: int | None,
    interval: float,
    reset: bool,
    steam_id: str,
    cfg: Any,
    http: market.Http | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Точка входа: по умолчанию dry-run, действия — только по --sell/--grind."""
    if reset:
        state.reset()
        log.info("Состояние распродажи сброшено")
        return

    status: Literal["ok", "interrupted", "error", "dry_run"] = "ok"
    rows: list[Row] = []
    sold = Result()
    ground = Result()
    try:
        if http is None:
            cookies = get_web_cookies("", interactive=False)
            if cookies is None:
                raise market.AuthExpired(
                    "нет действующей веб-сессии Steam — войдите через "
                    "app.cookies.playwright"
                )
            http = SteamHttp(cookies["steamLoginSecure"])
        ensure = getattr(http, "ensure_session", None)
        if ensure is not None:
            ensure(steam_id)

        inventory = items.fetch_inventory(steam_id, http.get_json)
        handled = state.load_handled()
        inventory = [it for it in inventory if int(it.assetid) not in handled]
        log.info("Инвентарь: %d предметов к рассмотрению", len(inventory))
        badge_levels = badges.fetch_badge_levels(
            cfg.steam_api_key, steam_id, http.get_json
        )
        sack = market.get_quote(http, SACK_NAME)
        if sack is None:
            raise SAMError("не удалось получить цену мешка самоцветов")
        m = fees.min_fee(sack.currency)
        rows = build_plan(
            http,
            inventory,
            badge_levels=badge_levels,
            sack_quote=sack,
            m=m,
            sleep=sleep,
        )
        _summarize(rows)
        if list_only:
            _print_plan(rows)
            return

        budget = limit
        if do_sell:
            # Сначала лоты по заявке (покупают сразу), потом по цене продажи:
            # --limit 1 первым делом проверяет мгновенную продажу.
            todo = [
                r for r in rows if r.decision.action in ("sell_bid", "sell_ask")
            ]
            todo.sort(key=lambda r: r.decision.action != "sell_bid")
            todo = todo if budget is None else todo[:budget]
            if budget is not None:
                budget -= len(todo)
            if todo:
                log.info("Выставление лотов: %d", len(todo))
                sold = sell(
                    http, steam_id, todo, interval=interval, sleep=sleep
                )
        if do_grind and not sold.auth_fail and not sold.hit_wall:
            todo = [r for r in rows if r.decision.action == "grind"]
            todo = todo if budget is None else todo[: max(budget, 0)]
            if todo:
                log.info("Разбор на самоцветы: %d", len(todo))
                ground = grind(
                    http, steam_id, todo, interval=interval, sleep=sleep
                )
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except (market.AuthExpired, SAMError) as e:
        status = "error"
        log.error("Распродажа остановлена: %s", e)
    except Exception:
        status = "error"
        log.exception("Прервано ошибкой.")

    if (sold.auth_fail or ground.auth_fail) and status == "ok":
        status = "error"

    try:
        if not (do_sell or do_grind) and status == "ok":
            n = sum(1 for r in rows if r.decision.action != "skip")
            report_result(
                status="dry_run",
                added=n,
                refused=0,
                error=0,
                hit_wall=False,
                cfg=cfg,
                title=_TITLE,
                done_word="к продаже или разбору",
                dry_head="dry-run (ничего не выставлено и не разобрано)",
            )
        else:
            log.info(SEPARATOR)
            log.info(
                "Выставлено %d (ждут подтверждения в Steam Guard: %d) на "
                "≈ %s руб на руки; разобрано %d (+%d самоцветов)",
                sold.done,
                sold.pending,
                _rub(sold.received_total),
                ground.done,
                ground.gems_total,
            )
            report_result(
                status=status,
                added=ground.done,
                refused=sold.refused + ground.refused,
                error=sold.error + ground.error,
                hit_wall=sold.hit_wall or ground.hit_wall,
                cfg=cfg,
                title=_TITLE,
                done_word=(
                    f"выставлено {sold.done} (ждут подтверждения "
                    f"{sold.pending}), разобрано"
                ),
            )
    except BaseException:
        # Отчёт — терминальный шаг: Ctrl+C здесь не должен выходить трейсбеком.
        log.exception("Не удалось сформировать финальный отчёт.")
