"""Оркестрация авто-добавления бесплатных игр Steam: discover + add фазы."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.free_games import discovery, licenses, report, state
from app.logging_setup import SEPARATOR
from app.steam.packageinfo import expand_packages_to_apps
from app.steam.steam_cm import cm_session
from app.steam.steam_local import find_steam_path

log = logging.getLogger("sam_automation")


def discover(*, include_demos: bool = True) -> list[int]:
    """Фаза discover: витрина free → candidates.txt минус owned/added/refused.

    owned вычисляется из client.licenses живой CM-сессии (authoritative для
    аккаунта) через expand_packages_to_apps — тот же путь, что и scan.py.
    Отсутствие Steam или неуспех CM-логина НЕ роняет discover — просто owned
    не вычитается (кандидаты могут включать уже имеющееся, лишнее отсеется
    на фазе add как DuplicateRequest/refused).
    """
    log.info(SEPARATOR)
    discovered = discovery.discover_candidates(include_demos=include_demos)
    log.info("Store search: всего обнаружено кандидатов: %d", len(discovered))

    steam_path = find_steam_path()
    owned: set[int] = set()
    if steam_path:
        with cm_session() as client:
            if client is not None:
                owned_packages = set(client.licenses.keys())
                owned = set(expand_packages_to_apps(steam_path, owned_packages))
                log.info("Steam CM: уже в библиотеке (owned): %d", len(owned))
            else:
                log.warning(
                    "Steam CM: вход не удался — owned не вычтен, кандидаты "
                    "могут включать уже имеющиеся игры"
                )
    else:
        log.warning("Папка Steam не найдена — owned не вычтен")

    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    candidates = [
        a
        for a in discovered
        if a not in owned
        and a not in already_added
        and a not in already_refused
    ]
    state.save_candidates(candidates)
    log.info(
        "Кандидатов к добавлению (минус owned/added/refused): %d",
        len(candidates),
    )
    return candidates


def add(*, limit: int | None = None) -> licenses.AddResult:
    """Фаза add: request_free_license батчами по candidates.txt (resume-aware)."""
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
        return licenses.AddResult()

    log.info(SEPARATOR)
    log.info("Добавление бесплатных лицензий: %d кандидатов", len(pending))

    with cm_session() as client:
        if client is None:
            log.error("Steam CM: вход не удался — добавление невозможно")
            for appid in pending:
                state.mark_error(appid)
            return licenses.AddResult(error=list(pending))
        result = licenses.add_licenses(client, pending)

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
    include_demos: bool,
    cfg: Any,
) -> None:
    """Точка входа: dry-run по умолчанию, реально добавляет только при do_add=True.

    discover() и add() (если do_add) выполняются под общим try/except —
    Ctrl+C/исключение ВО ВРЕМЯ discover() (включая CM-логин) раньше уходили
    необработанным трейсбеком мимо честного отчёта; теперь оба случая дают
    status="interrupted"/"error", как и сбой во время add().
    """
    if list_only:
        listed_candidates = state.load_candidates()
        for appid in listed_candidates:
            print(appid)
        log.info("Кандидатов в candidates.txt: %d", len(listed_candidates))
        return

    status: Literal["ok", "interrupted", "error", "dry_run"] = "ok"
    candidates: list[int] = []
    result = licenses.AddResult()
    try:
        candidates = discover(include_demos=include_demos)
        if do_add:
            result = add(limit=limit)
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except Exception:
        status = "error"
        log.exception("Прервано ошибкой.")

    if not do_add and status == "ok":
        report.report_result(
            status="dry_run",
            added=len(candidates),
            refused=0,
            error=0,
            hit_cap=False,
            cfg=cfg,
        )
        return

    report.report_result(
        status=status,
        added=len(result.added),
        refused=len(result.refused),
        error=len(result.error),
        hit_cap=result.hit_cap,
        cfg=cfg,
    )
