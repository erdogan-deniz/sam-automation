"""Чистка вишлиста: удаление бесплатного (B-17) и не вышедшего (B-18).

Правило владельца 19.10.2026: в вишлисте только платное и вышедшее;
бесплатное забирает в библиотеку add_free_games.py. fill_wishlist.py с 19.10.2026
такое не добавляет, а этот модуль убирает добавленное раньше.

Удаление — POST IWishlistService/RemoveFromWishlist тем же путём, что и
добавление (wishlist_api.add_pending с call=remove_from_wishlist): тот же
backoff на rate-limit и та же стена. Удалённое выпадает и из added.txt
вишлиста — иначе не вышедшая игра не вернулась бы в кандидатов, когда выйдет.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.cookies import get_web_cookies
from app.logging_setup import SEPARATOR
from app.wishlist import clean_state, discovery, report, wishlist_api
from app.wishlist import state as wishlist_state

log = logging.getLogger("sam_automation")

REASONS = ("free", "unreleased")
ALL_REASONS = frozenset(REASONS)

_TITLE = "Чистка Wishlist"


def discover(
    *, steam_id: str, reasons: frozenset[str] = ALL_REASONS
) -> list[int]:
    """Вишлист → кандидаты на удаление по выбранным причинам → candidates.txt.

    Сбой GetWishlist или проверки магазина пробрасывается до save_candidates:
    старый список не затирается неполным.
    """
    log.info(SEPARATOR)
    wishlisted = sorted(discovery.fetch_wishlist_ids(steam_id))
    log.info("Wishlist: позиций в вишлисте: %d", len(wishlisted))
    flags = discovery.fetch_store_flags(wishlisted)
    chosen: set[int] = set()
    if "free" in reasons:
        chosen |= flags.free
    if "unreleased" in reasons:
        chosen |= flags.coming_soon
    candidates = [a for a in wishlisted if a in chosen]
    clean_state.save_candidates(candidates)
    log.info(
        "Wishlist: бесплатных %d, не вышедших %d — к удалению (%s): %d",
        len(flags.free),
        len(flags.coming_soon),
        ", ".join(r for r in REASONS if r in reasons),
        len(candidates),
    )
    return candidates


def remove(
    *, limit: int | None = None, interval: float = 1.0
) -> wishlist_api.AddResult:
    """Удаляет кандидатов по одному. AddResult.added здесь — удалённые."""
    already = clean_state.load_removed_ids()
    pending = [a for a in clean_state.load_candidates() if a not in already]
    if limit is not None:
        pending = pending[:limit]
    if not pending:
        log.info("Нечего удалять")
        return wishlist_api.AddResult()

    log.info(SEPARATOR)
    log.info("Удаление из вишлиста: %d позиций", len(pending))

    cookies = get_web_cookies("", interactive=False)
    if cookies is None:
        log.error("Steam: нет действующей веб-сессии — удаление невозможно")
        return wishlist_api.AddResult(auth_fail=True)

    def _persist(appid: int, outcome: str) -> None:
        # По мере решения каждого appid — переживает жёсткий килл процесса.
        if outcome == "added":
            clean_state.mark_removed(appid)
            wishlist_state.unmark_added(appid)

    access_token = cookies["steamLoginSecure"].split("||", 1)[1]
    return wishlist_api.add_pending(
        access_token,
        pending,
        interval=interval,
        persist=_persist,
        call=wishlist_api.remove_from_wishlist,
    )


def run(
    *,
    do_remove: bool,
    list_only: bool,
    limit: int | None,
    interval: float,
    steam_id: str,
    cfg: Any,
    reasons: frozenset[str] = ALL_REASONS,
) -> None:
    """Точка входа: dry-run по умолчанию, удаляет только при do_remove=True."""
    if list_only:
        listed = clean_state.load_candidates()
        for appid in listed:
            print(appid)
        log.info("Кандидатов на удаление: %d", len(listed))
        return

    status: Literal["ok", "interrupted", "error", "dry_run"] = "ok"
    candidates: list[int] = []
    result = wishlist_api.AddResult()
    try:
        candidates = discover(steam_id=steam_id, reasons=reasons)
        if do_remove:
            result = remove(limit=limit, interval=interval)
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except Exception:
        status = "error"
        log.exception("Прервано ошибкой.")

    if result.auth_fail and status == "ok":
        status = "error"

    try:
        if not do_remove and status == "ok":
            report.report_result(
                status="dry_run",
                added=len(candidates),
                refused=0,
                error=0,
                hit_wall=False,
                cfg=cfg,
                title=_TITLE,
                done_word="к удалению",
                dry_head="dry-run (ничего не удалено)",
            )
        else:
            report.report_result(
                status=status,
                added=len(result.added),
                refused=len(result.refused),
                error=len(result.error),
                hit_wall=result.hit_wall,
                cfg=cfg,
                title=_TITLE,
                done_word="удалено",
            )
    except BaseException:
        # Отчёт — терминальный шаг: Ctrl+C в этот момент не должен выйти
        # сырым трейсбеком, статус уже посчитан (как в orchestrate.run).
        log.exception("Не удалось сформировать финальный отчёт.")
