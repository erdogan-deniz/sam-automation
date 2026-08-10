"""Сверка bookkeeping (added.txt) с реальным состоянием Steam.

Слепая зона full-project-аудита 2026-08-10 (#5): весь предыдущий аудит
проверял только внутреннюю самосогласованность bookkeeping (added.txt/
refused.txt/etc.) — ничего не сверяло, отражает ли она правду. v1 — только
free_games и wishlist: оба дают весь список ОДНИМ вызовом (GetOwnedGames/
GetWishlist), поэтому сверка дешева независимо от размера библиотеки.
Achievements сюда сознательно не входит — GetPlayerAchievements не имеет
batch-варианта (по игре за вызов), полный свип на большой библиотеке — часы;
это отдельная, более дорогая задача.

Ничего не чинит и не пишет в data/ — только сообщает расхождения. Не требует
SAM/run-lock (как scan.py) — чистый Steam API read-only отчёт.

Использование:
    python scripts/verify/ground_truth.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import logging

from app.config import load_config
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


def main() -> None:
    """Сверяет added.txt free_games и wishlist с реальным состоянием Steam."""
    print()
    setup_logging(name="ground_truth", category="verify/ground_truth")
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

    log.info(SEPARATOR)
    log.info("Free games: added.txt vs GetOwnedGames")
    mismatched_free = _check_free_games(cfg.steam_api_key, cfg.steam_id)
    if mismatched_free:
        log.warning(
            "%d appid в added.txt НЕ найдены среди owned (потерянный "
            "персист?): %s",
            len(mismatched_free),
            mismatched_free,
        )
    else:
        log.info("Расхождений нет — все added.txt реально owned")

    log.info(SEPARATOR)
    log.info("Wishlist: added.txt vs GetWishlist")
    mismatched_wishlist = _check_wishlist(cfg.steam_id)
    if mismatched_wishlist:
        log.warning(
            "%d appid в added.txt НЕ найдены в реальном вишлисте: %s",
            len(mismatched_wishlist),
            mismatched_wishlist,
        )
    else:
        log.info("Расхождений нет — все added.txt реально в вишлисте")

    log.info(SEPARATOR)
    if mismatched_free or mismatched_wishlist:
        log.warning("Сверка завершена С РАСХОЖДЕНИЯМИ — см. выше")
        sys.exit(1)
    log.info("Сверка завершена — bookkeeping соответствует Steam")


if __name__ == "__main__":
    main()
