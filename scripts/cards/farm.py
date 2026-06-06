"""SAM Card Farming — автоматический фарм Steam trading card drops.

Открывает игры через SAM.Game.exe (создаёт фейковую игровую сессию),
периодически проверяет через Steam Community, остались ли card drops.
Закрывает игру как только drops заканчиваются, открывает следующую.

Использование:
    python scripts/cards/farm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import atexit
import logging
import subprocess
import time
from collections import deque
from typing import Any

from app.cache import load_game_names
from app.cards import (
    check_cards_remaining,
    fetch_games_with_card_drops,
    mark_card_done,
)
from app.config import load_config
from app.logging_setup import SEPARATOR, setup_logging
from app.notify import toast
from app.run_lock import acquire_run_lock, release_run_lock
from app.sam import check_steam_running, ensure_sam, kill_process, launch_game
from app.steam import get_web_cookies, resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")

_MAX_CHECK_FAILURES = (
    5  # после N неудачных проверок подряд считаем дропы закончившимися
)
_PAUSE_AFTER_KILL = (
    10  # сек, даём Steam обновить данные после закрытия SAM.Game.exe
)
_PAUSE_BETWEEN_GAMES = 3  # сек, пауза перед открытием следующей игры из очереди


def _kill_game(appid: int, proc: subprocess.Popen) -> None:
    """Завершает SAM.Game.exe."""
    kill_process(proc)


def _open_next(
    queue: deque[tuple[int, int]],
    active: dict[int, subprocess.Popen],
    cfg: Any,
    game_names: dict,
) -> None:
    """Открывает следующую игру из очереди если есть место."""
    while queue and len(active) < cfg.max_concurrent_games:
        appid, cnt = queue.popleft()
        time.sleep(_PAUSE_BETWEEN_GAMES)
        proc = launch_game(cfg.sam_game_exe_path, appid)
        active[appid] = proc
        name = game_names.get(appid, "")
        if name:
            log.info("APP NAME: %s", name)
        log.info("APP PID: %d", proc.pid)
        if cnt >= 0:
            log.info("APP CARDS: %d", cnt)
        log.info(SEPARATOR)


def _farm_loop(
    games_with_drops: list[tuple[int, int]],
    cfg: Any,
    cookies: dict[str, str],
    steam_id: str,
) -> None:
    """Основной цикл фарма: открывает игры, периодически проверяет дропы."""
    queue: deque[tuple[int, int]] = deque(games_with_drops)
    active: dict[int, subprocess.Popen] = {}
    check_failures: dict[int, int] = {}
    game_names = load_game_names()

    log.info(SEPARATOR)
    log.info(
        "Время интервала проверки приложений библиотеки Steam с доступными картами на выпадение: %d мин",
        cfg.card_check_interval,
    )
    log.info(
        "Параллельно запущено приложений библиотеки Steam с доступными картами на выпадение: %d",
        cfg.max_concurrent_games,
    )
    log.info(SEPARATOR)

    _open_next(queue, active, cfg, game_names)

    try:
        while active:
            log.info(
                "До следующей проверки осталось %d минут ...",
                cfg.card_check_interval,
            )
            log.info(SEPARATOR)
            time.sleep(cfg.card_check_interval * 60)

            for appid in list(active):
                remaining = check_cards_remaining(cookies, steam_id, appid)
                time.sleep(1.0)  # пауза между запросами

                if remaining == 0:
                    log.info("APP ID: %d — Card drops закончились", appid)
                    _kill_game(appid, active.pop(appid))
                    check_failures.pop(appid, None)
                    mark_card_done(appid)
                    _open_next(queue, active, cfg, game_names)
                elif remaining > 0:
                    _kill_game(appid, active[appid])
                    time.sleep(_PAUSE_AFTER_KILL)
                    proc = launch_game(cfg.sam_game_exe_path, appid)
                    active[appid] = proc
                    name = game_names.get(appid, "")
                    if name:
                        log.info("APP NAME: %s", name)
                    log.info("APP PID: %d", proc.pid)
                    log.info("APP CARDS: %d", remaining)
                    log.info(SEPARATOR)
                    check_failures[appid] = 0
                else:
                    failures = check_failures.get(appid, 0) + 1
                    check_failures[appid] = failures
                    if failures >= _MAX_CHECK_FAILURES:
                        _kill_game(appid, active.pop(appid))
                        check_failures.pop(appid, None)
                        mark_card_done(appid)
                        _open_next(queue, active, cfg, game_names)
                    else:
                        _kill_game(appid, active[appid])
                        time.sleep(_PAUSE_AFTER_KILL)
                        proc = launch_game(cfg.sam_game_exe_path, appid)
                        active[appid] = proc
                        name = game_names.get(appid, "")
                        if name:
                            log.info("APP NAME: %s", name)
                        log.info("APP PID: %d", proc.pid)
                        log.info(SEPARATOR)

    except KeyboardInterrupt:
        log.info("Прервано (Ctrl+C). Закрываю все активные игры...")
    finally:
        for appid, proc in active.items():
            _kill_game(appid, proc)

    log.info(SEPARATOR)
    log.info("Card farming завершён")
    log.info(SEPARATOR)
    toast("SAM Automation — Cards", "Card farming завершён")


def main() -> None:
    """Точка входа: запускает цикл фарма trading cards."""
    print()
    setup_logging(verbose=False, name="farm_cards", category="cards/farm")
    try:
        acquire_run_lock("cards/farm")
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)
    atexit.register(release_run_lock)
    log.info("SAM Automation: Farm Cards")
    log.info(SEPARATOR)
    cfg = load_config()
    validate(cfg)

    if not check_steam_running():
        log.error("Steam не запущен! Запусти Steam и попробуй снова.")
        sys.exit(1)
    log.info("Steam клиент приложение запущено ✓")
    log.info("Использование сохранённого Steam cookie ✓")
    log.info(SEPARATOR)

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

    log.info(
        "Поиск приложений библиотеки Steam с доступными картами на выпадение ..."
    )
    cookies = get_web_cookies(cfg.steam_id)
    if not cookies:
        log.error(
            "Нет авторизации Steam. Запусти скрипт вручную один раз:\n"
            "  python scripts/cards/farm.py\n"
            "и введи 2FA код при запросе '[Steam JWT] Введи 2FA код'."
        )
        sys.exit(1)

    games_with_drops = fetch_games_with_card_drops(cookies, steam_id)
    if not games_with_drops:
        log.info("Нет игр с оставшимися card drops — всё уже получено!")
        sys.exit(0)

    _farm_loop(games_with_drops, cfg, cookies, steam_id)


if __name__ == "__main__":
    main()
