"""Оркестрация авто-добавления каталога Steam в вишлист: discover + add фазы."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.cookies import get_web_cookies
from app.logging_setup import SEPARATOR
from app.wishlist import discovery, report, state, wishlist_api

log = logging.getLogger("sam_automation")


def discover(*, api_key: str, steam_id: str) -> list[int]:
    """Фаза discover: universe (GetAppList) минус owned/wishlisted (Web API)
    минус added/refused (state) → candidates.txt."""
    log.info(SEPARATOR)
    discovered = discovery.discover_candidates(
        api_key=api_key, steam_id=steam_id
    )
    log.info(
        "Wishlist: обнаружено кандидатов (минус owned/wishlisted): %d",
        len(discovered),
    )

    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    candidates = [
        a
        for a in discovered
        if a not in already_added and a not in already_refused
    ]
    state.save_candidates(candidates)
    log.info(
        "Кандидатов к добавлению (минус added/refused): %d", len(candidates)
    )
    return candidates


def add(
    *, limit: int | None = None, interval: float = 1.0
) -> wishlist_api.AddResult:
    """Фаза add: добавляет pending appid по одному (resume-aware).

    Сбой веб-сессии (нет cookie вовсе, или add_pending вернул auth_fail) НЕ
    помечает appid в error.txt — это сбой сессии, не транзиент конкретного
    appid; пользователь просто перезапустит --add после восстановления
    сессии, без --retry-errors (отличие от free_games, где CM-login-failure
    метит ВСЕ pending как error — там сессия внутри cm_session() ближе к
    per-run ресурсу, не хранится между запусками).
    """
    candidates = state.load_candidates()
    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    already_error = state.load_error_ids()
    pending = [
        a
        for a in candidates
        if a not in already_added
        and a not in already_refused
        and a not in already_error
    ]
    if limit is not None:
        pending = pending[:limit]

    if not pending:
        log.info("Нет кандидатов к добавлению")
        return wishlist_api.AddResult()

    log.info(SEPARATOR)
    log.info("Добавление в вишлист: %d кандидатов", len(pending))

    cookies = get_web_cookies("", interactive=False)
    if cookies is None:
        log.error("Steam: нет действующей веб-сессии — добавление невозможно")
        return wishlist_api.AddResult(auth_fail=True)

    access_token = cookies["steamLoginSecure"].split("||", 1)[1]
    result = wishlist_api.add_pending(access_token, pending, interval=interval)

    if result.auth_fail:
        remaining = [
            a
            for a in pending
            if a not in result.added and a not in result.refused
        ]
        log.warning(
            "Wishlist: сессия истекла (401) — одна попытка обновить токен"
        )
        cookies = get_web_cookies("", interactive=False)
        if cookies is not None:
            access_token = cookies["steamLoginSecure"].split("||", 1)[1]
            retry = wishlist_api.add_pending(
                access_token, remaining, interval=interval
            )
            result.added.extend(retry.added)
            result.refused.extend(retry.refused)
            result.error.extend(retry.error)
            result.hit_wall = result.hit_wall or retry.hit_wall
            result.auth_fail = retry.auth_fail
        # else: остаётся auth_fail=True, remaining НЕ помечен error — resume подхватит

    for appid in result.added:
        state.mark_added(appid)
    for appid in result.refused:
        state.mark_refused(appid)
    for appid in result.error:
        state.mark_error(appid)

    return result


def run(
    *,
    do_add: bool,
    list_only: bool,
    limit: int | None,
    interval: float,
    api_key: str,
    steam_id: str,
    cfg: Any,
) -> None:
    """Точка входа: dry-run по умолчанию, реально добавляет только при do_add=True."""
    if list_only:
        listed_candidates = state.load_candidates()
        for appid in listed_candidates:
            print(appid)
        log.info("Кандидатов в candidates.txt: %d", len(listed_candidates))
        return

    status: Literal["ok", "interrupted", "error", "dry_run"] = "ok"
    candidates: list[int] = []
    result = wishlist_api.AddResult()
    try:
        candidates = discover(api_key=api_key, steam_id=steam_id)
        if do_add:
            result = add(limit=limit, interval=interval)
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except Exception:
        status = "error"
        log.exception("Прервано ошибкой.")

    if result.auth_fail and status == "ok":
        status = "error"

    if not do_add and status == "ok":
        report.report_result(
            status="dry_run",
            added=len(candidates),
            refused=0,
            error=0,
            hit_wall=False,
            cfg=cfg,
        )
        return

    report.report_result(
        status=status,
        added=len(result.added),
        refused=len(result.refused),
        error=len(result.error),
        hit_wall=result.hit_wall,
        cfg=cfg,
    )
