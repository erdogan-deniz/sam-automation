"""Оркестрация авто-добавления бесплатного контента Steam: discover + add фазы."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.free_games import discovery, licenses, report, state
from app.logging_setup import SEPARATOR
from app.steam.packageinfo import expand_packages_to_apps
from app.steam.steam_api import fetch_owned_games
from app.steam.steam_cm import cm_session
from app.steam.steam_local import find_steam_path
from app.wishlist.content import ALL_TYPES

log = logging.getLogger("sam_automation")


def discover(
    *, api_key: str = "", steam_id: str = "", types: frozenset[str] = ALL_TYPES
) -> list[int]:
    """Фаза discover: каталог Steam → candidates.txt минус owned/added/refused.

    owned — из client.licenses живой CM-сессии (authoritative, включая DLC)
    через expand_packages_to_apps, тот же путь, что у scan_library.py, плюс
    GetOwnedGames: по owned решается, к своей ли игре DLC. Отсутствие Steam,
    неуспех CM-логина или GetOwnedGames НЕ роняют discover — owned просто
    неполон (лишнее отсеется на фазе add как refused, DLC к играм без
    owned не попадут в кандидаты).
    """
    log.info(SEPARATOR)
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
    if api_key and steam_id:
        try:
            owned |= {
                int(g["appid"]) for g in fetch_owned_games(api_key, steam_id)
            }
        except Exception as e:
            log.warning("Steam API: GetOwnedGames не удался — %s", e)

    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    discovered = discovery.discover_candidates(
        api_key=api_key,
        types=types,
        owned=owned,
        exclude=owned | already_added | already_refused,
    )
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
    """Фаза add: request_free_license батчами по candidates.txt (resume-aware).

    persist инкрементально — по мере решения каждого батча в add_licenses —
    переживает жёсткий килл процесса посреди многоминутного retry-шторма
    (см. licenses.add_licenses.persist). Финальный проход по result.* после
    возврата избыточен на успешном пути (все appid уже персистнуты через
    persist), но остаётся страховкой — тот же паттерн, что в
    app.wishlist.orchestrate.add.
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
        return licenses.AddResult()

    log.info(SEPARATOR)
    log.info("Добавление бесплатных лицензий: %d кандидатов", len(pending))

    def _persist(appid: int, outcome: str) -> None:
        if outcome == "added":
            state.mark_added(appid)
        elif outcome == "refused":
            state.mark_refused(appid)
        else:
            state.mark_error(appid)

    with cm_session() as client:
        if client is None:
            log.error("Steam CM: вход не удался — добавление невозможно")
            for appid in pending:
                state.mark_error(appid)
            return licenses.AddResult(error=list(pending))
        result = licenses.add_licenses(client, pending, persist=_persist)

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
    cfg: Any,
    types: frozenset[str] = ALL_TYPES,
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
        candidates = discover(
            api_key=getattr(cfg, "steam_api_key", ""),
            steam_id=getattr(cfg, "steam_id", ""),
            types=types,
        )
        if do_add:
            result = add(limit=limit)
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except Exception:
        status = "error"
        log.exception("Прервано ошибкой.")

    if not do_add and status == "ok":
        try:
            report.report_result(
                status="dry_run",
                added=len(candidates),
                refused=0,
                error=0,
                hit_cap=False,
                cfg=cfg,
            )
        except BaseException:
            # Отчёт — терминальный шаг: третий Ctrl+C ровно в этот момент
            # (BaseException) не должен пробрасываться из run() сырым
            # трейсбеком — статус уже честно посчитан (см. boost_playtime.py).
            log.exception("Не удалось сформировать финальный отчёт.")
        return

    try:
        report.report_result(
            status=status,
            added=len(result.added),
            refused=len(result.refused),
            error=len(result.error),
            hit_cap=result.hit_cap,
            session_dead=result.session_dead,
            stalled=result.stalled,
            cfg=cfg,
        )
    except BaseException:
        log.exception("Не удалось сформировать финальный отчёт.")
