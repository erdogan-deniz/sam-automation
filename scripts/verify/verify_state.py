"""Сверка bookkeeping (added.txt) с реальным состоянием Steam.

Слепая зона full-project-аудита 2026-08-10 (#5): весь предыдущий аудит
проверял только внутреннюю самосогласованность bookkeeping (added.txt/
refused.txt/etc.) — ничего не сверяло, отражает ли она правду. v1 — только
free_games и wishlist: оба дают весь список ОДНИМ вызовом (GetOwnedGames/
GetWishlist), поэтому сверка дешева независимо от размера библиотеки.
demos (2026-09-12, B-11) добавлены тем же способом — свой added.txt,
сверяется с тем же GetOwnedGames. Achievements сюда сознательно не входит —
GetPlayerAchievements не имеет batch-варианта (по игре за вызов), полный
свип на большой библиотеке — часы; это отдельная, более дорогая задача.

Ничего не чинит и не пишет в data/ — только сообщает расхождения. Не требует
SAM/run-lock (как scan_library.py) — чистый Steam API read-only отчёт.

Коды выхода: 0 — всё сверено, расхождений нет; 1 — найдены расхождения;
2 — расхождений не найдено, но часть проверок не выполнилась (сбой Steam API,
битый ответ) — «не проверено», а не «всё в порядке» и не «всё потеряно».

Использование:
    python scripts/verify/verify_state.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import logging

from app.config import load_config
from app.demos import state as demos_state
from app.free_games import state as free_games_state
from app.logging_setup import SEPARATOR, setup_logging
from app.steam import fetch_owned_games, resolve_steam_id
from app.validator import validate
from app.wishlist import state as wishlist_state
from app.wishlist.discovery import fetch_wishlist_ids

log = logging.getLogger("sam_automation")


def _check_free_games(api_key: str, steam_id: str) -> list[int]:
    """added.txt минус реально owned — сигнал потерянного персиста.

    Найденный отдельно High-баг (батч-персист add_licenses теряет уже
    выданные лицензии при killed-прогоне посреди retry-шторма) должен
    проявиться здесь именно так: appid в added.txt, которого нет в owned.
    """
    added = free_games_state.load_added_ids()
    if not added:
        return []
    owned = {int(g["appid"]) for g in fetch_owned_games(api_key, steam_id)}
    return sorted(added - owned)


def _check_demos(api_key: str, steam_id: str) -> list[int]:
    """added.txt (demos) минус реально owned — тот же класс сигнала, что
    _check_free_games, для отдельного bookkeeping app/demos (B-11).
    """
    added = demos_state.load_added_ids()
    if not added:
        return []
    owned = {int(g["appid"]) for g in fetch_owned_games(api_key, steam_id)}
    return sorted(added - owned)


def _check_wishlist(steam_id: str) -> list[int]:
    """added.txt минус реальный вишлист.

    wishlist уже персистит по одному appid сразу (не батчем), так что это
    скорее defense-in-depth, чем детектор известного класса бага.
    """
    added = wishlist_state.load_added_ids()
    if not added:
        return []
    live = fetch_wishlist_ids(steam_id)
    return sorted(added - live)


def _run_check(
    title: str,
    check: Callable[[], list[int]],
    mismatch_msg: str,
    ok_msg: str,
) -> list[int] | None:
    """Одна сверка; None — проверку выполнить не удалось.

    Сбой Steam API (RuntimeError из _api_get, битый ответ GetOwnedGames) —
    это «не проверено», а не «всё потеряно» и не сырой traceback: остальные
    проверки должны отработать.
    """
    log.info(SEPARATOR)
    log.info(title)
    try:
        mismatched = check()
    except Exception as e:
        log.error("Проверка НЕ выполнена: %s", e)
        return None
    if mismatched:
        log.warning(mismatch_msg, len(mismatched), mismatched)
    else:
        log.info(ok_msg)
    return mismatched


def main() -> None:
    """Сверяет added.txt free_games, wishlist и demos с реальным Steam."""
    print()
    setup_logging(name="verify_state", category="verify/verify_state")
    log.info("Сверка bookkeeping с реальным состоянием Steam")
    log.info(SEPARATOR)
    cfg = load_config()

    if cfg.steam_id:
        try:
            cfg.steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
        except (RuntimeError, KeyError) as e:
            log.error("Не удалось определить Steam ID: %s", e)
            sys.exit(1)

    validate(cfg)

    key, sid = cfg.steam_api_key, cfg.steam_id
    results = {
        "free games": _run_check(
            "Free games: added.txt vs GetOwnedGames",
            lambda: _check_free_games(key, sid),
            "%d appid в added.txt НЕ найдены среди owned (потерянный "
            "персист?): %s",
            "Расхождений нет — все added.txt реально owned",
        ),
        "wishlist": _run_check(
            "Wishlist: added.txt vs GetWishlist",
            lambda: _check_wishlist(sid),
            "%d appid в added.txt НЕ найдены в реальном вишлисте: %s",
            "Расхождений нет — все added.txt реально в вишлисте",
        ),
        "demos": _run_check(
            "Demos: added.txt vs GetOwnedGames",
            lambda: _check_demos(key, sid),
            "%d appid в added.txt (demos) НЕ найдены среди owned "
            "(потерянный персист?): %s",
            "Расхождений нет — все added.txt (demos) реально owned",
        ),
    }

    log.info(SEPARATOR)
    if any(results.values()):
        log.warning("Сверка завершена С РАСХОЖДЕНИЯМИ — см. выше")
        sys.exit(1)
    failed = [name for name, r in results.items() if r is None]
    if failed:
        log.error(
            "Сверка НЕ ЗАВЕРШЕНА — не удалось проверить: %s. Расхождений "
            "в остальном не найдено; повтори позже.",
            ", ".join(failed),
        )
        sys.exit(2)
    log.info("Сверка завершена — bookkeeping соответствует Steam")


if __name__ == "__main__":
    main()
