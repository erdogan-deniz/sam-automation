"""Boost Playtime — добивает playtime до playtime_target_minutes в каждой игре.

Запускает SAM.Game.exe для каждой игры (фейковая сессия → Steam считает playtime).
Batch-модель: N игр одновременно → ждём playtime_idle_duration сек → закрываем всех → следующий батч.

Источник правды — Steam API (`playtime_forever`), локальный прогресс не хранится.

Использование:
    python scripts/playtime/boost.py              # добить недостающие игры
    python scripts/playtime/boost.py --list       # показать недобранные игры и выйти
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import atexit
import logging
import subprocess
import time
from typing import Any

from app.cache import (
    ALL_IDS_FILE,
    clear_playtime_progress,
    load_game_names,
    load_playtime_done_ids,
    load_playtime_skip_ids,
    mark_playtime_done,
    mark_playtime_skip,
)
from app.config import load_config
from app.id_file import read_ids_ordered
from app.logging_setup import SEPARATOR, setup_logging
from app.notify import toast
from app.run_lock import acquire_run_lock, release_run_lock
from app.sam import (
    check_steam_running,
    drop_failed_launches,
    ensure_sam,
    kill_process,
    launch_games_staggered,
)
from app.steam import fetch_owned_games, resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")

# Пауза после убийства батча перед стартом следующего (сек). Даёт Steam
# освободить global user от закрытых сессий — иначе первая игра нового
# батча ловит 'failed to connect to global user'.
_PAUSE_AFTER_KILL = 5.0


def _build_parser() -> argparse.ArgumentParser:
    """CLI-флаги boost."""
    parser = argparse.ArgumentParser(
        description="Boost Playtime — набивает время во всех играх из all.txt"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать игры к набивке и выйти",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить прогресс (playtime/done.txt) и набить время заново",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _prepare_progress(args: argparse.Namespace) -> None:
    """Применяет флаг сброса прогресса до сбора списка игр."""
    if args.reset:
        clear_playtime_progress()
        log.info("Сброшен прогресс playtime (--reset)")


def _select_targets(
    all_ids: list[int],
    played: dict[int, int],
    skip: set[int],
    target: int,
    names: dict[int, str],
) -> list[dict]:
    """Игры из all_ids, которым нужно набить время (порядок сохранён).

    Пропускает игры из skip и те, у которых известный playtime >= target.
    Для игр без известного playtime (нет в `played`) считаем 0 — их идлим.
    """
    out: list[dict] = []
    for appid in all_ids:
        if appid in skip:
            continue
        pt = played.get(appid, 0)
        if pt >= target:
            continue
        out.append(
            {
                "appid": appid,
                "name": names.get(appid, str(appid)),
                "playtime_forever": pt,
            }
        )
    return out


def _fetch_targets(cfg: Any, steam_id: str) -> list[dict]:
    """Все игры из all.txt, которым нужно набить время.

    Вселенная — `all.txt` (полная библиотека). Steam Web API даёт playtime
    только для части игр; известные с playtime >= target пропускаем, остальные
    (в т.ч. free/демо/лицензии без данных API) идлим вслепую один раз.
    Пропускаем exclude_ids, playtime/skip.txt (не подключаются) и
    playtime/done.txt (уже набили — resume).
    """
    all_ids = read_ids_ordered(ALL_IDS_FILE)
    played = {
        g["appid"]: g.get("playtime_forever", 0)
        for g in fetch_owned_games(cfg.steam_api_key, steam_id)
    }
    skip = (
        set(cfg.exclude_ids)
        | load_playtime_skip_ids()
        | load_playtime_done_ids()
    )
    return _select_targets(
        all_ids, played, skip, cfg.playtime_target_minutes, load_game_names()
    )


def _boost_loop(games: list[dict], cfg: Any) -> None:
    """Batch-цикл: запустить N игр → ждать playtime_idle_duration → убить всех → следующий батч."""
    total = len(games)
    done_count = 0
    active: dict[int, subprocess.Popen] = {}

    log.info(SEPARATOR)
    log.info("Boost Playtime — начало работы")
    log.info(
        "Игр к обработке: %d | Параллельно: %d | Время айдла: %d сек",
        total,
        cfg.max_concurrent_games,
        cfg.playtime_idle_duration,
    )
    log.info(SEPARATOR)

    try:
        for i in range(0, total, cfg.max_concurrent_games):
            batch = games[i : i + cfg.max_concurrent_games]
            games_with_names = [
                (g["appid"], g.get("name", str(g["appid"]))) for g in batch
            ]
            active = launch_games_staggered(
                cfg.sam_game_exe_path, games_with_names
            )

            # Отсеять игры, не подключившиеся к Steam (playtest/демо и пр.)
            failed = drop_failed_launches(active)
            for appid in failed:
                mark_playtime_skip(appid)
            if failed:
                log.info("Не подключились к Steam (в skip): %d", len(failed))

            if active:
                log.info(
                    "Батч %d игр запущен, жду %d сек...",
                    len(active),
                    cfg.playtime_idle_duration,
                )
                time.sleep(cfg.playtime_idle_duration)

                for appid, proc in active.items():
                    kill_process(proc)
                    mark_playtime_done(appid)
                    log.info("[%d] Закрыт", appid)

            done_count += len(active) + len(failed)
            log.info("Прогресс: %d / %d", done_count, total)

            # Пауза перед следующим батчем — даём Steam освободить сессии
            if i + cfg.max_concurrent_games < total:
                time.sleep(_PAUSE_AFTER_KILL)

    except KeyboardInterrupt:
        log.info("Прервано (Ctrl+C). Закрываю активные игры...")
        for appid, proc in active.items():
            kill_process(proc)
        # Не помечаем как done — батч мог не набрать достаточно времени

    log.info(SEPARATOR)
    log.info("Boost Playtime завершён. Обработано: %d / %d", done_count, total)
    log.info(SEPARATOR)
    toast(
        "SAM Automation — Playtime",
        f"Готово: {done_count} / {total} игр обработано",
    )


def main() -> None:
    """Точка входа: парсит аргументы CLI и запускает цикл набивки playtime."""
    args = _build_parser().parse_args()

    setup_logging(
        verbose=args.verbose, name="boost_playtime", category="playtime/boost"
    )
    cfg = load_config()
    validate(cfg)
    _prepare_progress(args)

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

    log.info("Собираю игры для набивки из all.txt (вся библиотека)...")
    games = _fetch_targets(cfg, steam_id)
    log.info("Игр к набивке (без уже набитых и наигранных): %d", len(games))

    if not games:
        log.info("Нет игр для обработки!")
        sys.exit(0)

    batches = (len(games) + cfg.max_concurrent_games - 1) // (
        cfg.max_concurrent_games
    )
    est_min = batches * (cfg.playtime_idle_duration + _PAUSE_AFTER_KILL) / 60
    log.info(
        "Оценка: ~%.0f мин (%d батчей). Прерывание безопасно — resume по "
        "playtime/done.txt",
        est_min,
        batches,
    )

    if args.list:
        for g in games:
            pt = g.get("playtime_forever", 0)
            print(f"{g['appid']:>10}  [{pt:>3} мин]  —  {g.get('name', '?')}")
        sys.exit(0)

    try:
        acquire_run_lock("playtime/boost")
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)
    atexit.register(release_run_lock)
    _boost_loop(games, cfg)


if __name__ == "__main__":
    main()
