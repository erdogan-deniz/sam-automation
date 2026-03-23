"""Boost Playtime — набивает 1+ мин playtime в играх с нулевым временем.

Запускает SAM.Game.exe для каждой игры (фейковая сессия → Steam считает playtime).
Batch-модель: N игр одновременно → ждём playtime_idle_duration сек → закрываем всех → следующий батч.

Использование:
    python scripts/playtime/boost.py              # начать/продолжить
    python scripts/playtime/boost.py --list       # показать игры с 0 playtime и выйти
    python scripts/playtime/boost.py --reset      # сбросить прогресс и начать заново
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import subprocess
import time

from app.cache import (
    clear_playtime_progress,
    load_playtime_done_ids,
    mark_playtime_done,
)
from app.config import load_config
from app.logging_setup import setup_logging
from app.validator import validate
from app.sam import check_steam_running, ensure_sam, kill_process, launch_game
from app.steam import fetch_owned_games, resolve_steam_id

log = logging.getLogger("sam_automation")


def _fetch_unplayed(cfg, steam_id: str) -> list[dict]:
    """Возвращает игры с playtime_forever == 0, не из done_ids и не из exclude_ids."""
    games = fetch_owned_games(cfg.steam_api_key, steam_id)
    done = load_playtime_done_ids()
    exclude = set(cfg.exclude_ids)
    return [
        g
        for g in games
        if g.get("playtime_forever", 0) == 0
        and g["appid"] not in done
        and g["appid"] not in exclude
    ]


def _boost_loop(games: list[dict], cfg) -> None:
    """Batch-цикл: запустить N игр → ждать playtime_idle_duration → убить всех → следующий батч."""
    total = len(games)
    done_count = 0
    active: dict[int, subprocess.Popen] = {}

    log.info("=" * 60)
    log.info("Boost Playtime — начало работы")
    log.info(
        "Игр к обработке: %d | Параллельно: %d | Время айдла: %d сек",
        total,
        cfg.max_concurrent_games,
        cfg.playtime_idle_duration,
    )
    log.info("=" * 60)

    try:
        for i in range(0, total, cfg.max_concurrent_games):
            batch = games[i : i + cfg.max_concurrent_games]
            active = {}

            for g in batch:
                appid = g["appid"]
                name = g.get("name", str(appid))
                log.info("[%d] Запускаю: %s", appid, name)
                active[appid] = launch_game(cfg.sam_game_exe_path, appid)

            log.info(
                "Батч %d игр запущен, жду %d сек...",
                len(active),
                cfg.playtime_idle_duration,
            )
            time.sleep(cfg.playtime_idle_duration)

            for appid, proc in active.items():
                kill_process(proc)
                mark_playtime_done(appid)
                log.info("[%d] Закрыт и отмечен как done", appid)

            done_count += len(active)
            log.info("Прогресс: %d / %d", done_count, total)

    except KeyboardInterrupt:
        log.info("Прервано (Ctrl+C). Закрываю активные игры...")
        for appid, proc in active.items():
            kill_process(proc)
        # Не помечаем как done — батч мог не набрать достаточно времени

    log.info("=" * 60)
    log.info("Boost Playtime завершён. Обработано: %d / %d", done_count, total)
    log.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Boost Playtime — набивает 1+ мин в играх с нулевым playtime"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать игры с 0 playtime и выйти",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить прогресс и начать заново",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(
        verbose=args.verbose, name="boost_playtime", category="playtime/boost"
    )
    cfg = load_config()
    validate(cfg)

    if args.reset:
        clear_playtime_progress()
        log.info("Прогресс playtime boosting сброшен")

    if not check_steam_running():
        log.error("Steam не запущен! Запусти Steam и попробуй снова.")
        sys.exit(1)
    log.info("Steam запущен")

    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    try:
        steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
    except RuntimeError as e:
        log.error("Не удалось определить Steam ID: %s", e)
        sys.exit(1)
    log.info("Steam ID: %s", steam_id)

    log.info("Получаю список игр с 0 playtime через Steam API...")
    games = _fetch_unplayed(cfg, steam_id)
    already_done = len(load_playtime_done_ids())

    log.info(
        "Игр с 0 playtime (не обработано): %d (уже готово: %d)",
        len(games),
        already_done,
    )

    if not games:
        log.info("Нет игр для обработки!")
        sys.exit(0)

    if args.list:
        for g in games:
            print(f"{g['appid']:>10}  —  {g.get('name', '?')}")
        sys.exit(0)

    _boost_loop(games, cfg)


if __name__ == "__main__":
    main()
