"""SAM Card Farming — автоматический фарм Steam trading card drops.

Открывает игры через SAM.Game.exe (создаёт фейковую игровую сессию),
периодически проверяет через Steam Community, остались ли card drops.
Закрывает игру как только drops заканчиваются, открывает следующую.

Использование:
    python scripts/cards/farm.py              # начать/продолжить фарм
    python scripts/cards/farm.py --list       # показать игры с card drops
    python scripts/cards/farm.py --reset      # сбросить прогресс и начать заново
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import subprocess
import time
from collections import deque
from typing import Any

from app.cards import (
    check_cards_remaining,
    clear_card_progress,
    fetch_games_with_card_drops,
    mark_card_done,
)
from app.config import load_config
from app.logging_setup import setup_logging
from app.validator import validate
from app.sam import check_steam_running, ensure_sam, kill_process, launch_game
from app.steam import fetch_owned_games, get_web_cookies, resolve_steam_id

log = logging.getLogger("sam_automation")

_MAX_CHECK_FAILURES = (
    5  # после N неудачных проверок подряд считаем дропы закончившимися
)


def _kill_game(appid: int, proc: subprocess.Popen) -> None:
    """Завершает SAM.Game.exe и логирует."""
    kill_process(proc)
    log.info("[%d] SAM.Game.exe закрыт", appid)


def _open_next(queue: deque[tuple[int, int]], active: dict[int, subprocess.Popen], cfg: Any) -> None:
    """Открывает следующую игру из очереди если есть место."""
    while queue and len(active) < cfg.max_concurrent_games:
        appid, cnt = queue.popleft()
        drops_str = str(cnt) if cnt >= 0 else "?"
        log.info(
            "[%d] Открываю для idle (%s drops remaining)", appid, drops_str
        )
        active[appid] = launch_game(cfg.sam_game_exe_path, appid)


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

    log.info("=" * 60)
    log.info("SAM Card Farming — начало работы")
    log.info(
        "Игр к обработке: %d | Параллельно: %d | Интервал проверки: %d мин",
        len(games_with_drops),
        cfg.max_concurrent_games,
        cfg.card_check_interval,
    )
    log.info("=" * 60)

    _open_next(queue, active, cfg)

    try:
        while active:
            log.info(
                "Idle: %s | Ожидаю %d мин до следующей проверки...",
                list(active.keys()),
                cfg.card_check_interval,
            )
            time.sleep(cfg.card_check_interval * 60)

            for appid in list(active):
                remaining = check_cards_remaining(cookies, steam_id, appid)
                time.sleep(1.0)  # пауза между запросами

                if remaining == 0:
                    log.info(
                        "[%d] Card drops закончились — закрываю игру", appid
                    )
                    _kill_game(appid, active.pop(appid))
                    check_failures.pop(appid, None)
                    mark_card_done(appid)
                    _open_next(queue, active, cfg)
                elif remaining > 0:
                    log.info(
                        "[%d] Ещё %d card drop(s) — продолжаю idle",
                        appid,
                        remaining,
                    )
                    check_failures[appid] = 0
                else:
                    failures = check_failures.get(appid, 0) + 1
                    check_failures[appid] = failures
                    if failures >= _MAX_CHECK_FAILURES:
                        log.warning(
                            "[%d] %d неудачных проверок подряд — считаю дропы закончившимися",
                            appid,
                            failures,
                        )
                        _kill_game(appid, active.pop(appid))
                        check_failures.pop(appid, None)
                        mark_card_done(appid)
                        _open_next(queue, active, cfg)
                    else:
                        log.warning(
                            "[%d] Не удалось определить card drops (%d/%d) — продолжаю idle",
                            appid,
                            failures,
                            _MAX_CHECK_FAILURES,
                        )

    except KeyboardInterrupt:
        log.info("Прервано (Ctrl+C). Закрываю все активные игры...")
    finally:
        for appid, proc in active.items():
            _kill_game(appid, proc)

    log.info("=" * 60)
    log.info("Card farming завершён")
    log.info("=" * 60)


def main() -> None:
    """Точка входа: парсит аргументы CLI и запускает цикл фарма trading cards."""
    parser = argparse.ArgumentParser(description="SAM Card Farming")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать игры с оставшимися card drops и выйти",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить прогресс card farming и начать заново",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log = setup_logging(
        verbose=args.verbose, name="card_farming", category="cards/farm"
    )
    cfg = load_config()

    validate(cfg)

    if args.reset:
        clear_card_progress()
        log.info("Прогресс card farming сброшен")

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

    log.info("Получаю список игр с оставшимися card drops через badges page...")
    cookies = get_web_cookies(cfg.steam_id)
    if cookies:
        games_with_drops = fetch_games_with_card_drops(cookies, steam_id)
        log.info("Найдено %d игр с оставшимися дропами", len(games_with_drops))
    else:
        log.error(
            "Нет авторизации Steam. Запусти скрипт вручную один раз:\n"
            "  python scripts/cards/farm.py\n"
            "и введи 2FA код при запросе '[Steam JWT] Введи 2FA код'."
        )
        sys.exit(1)

    if not games_with_drops:
        log.info("Нет игр с оставшимися card drops — всё уже получено!")
        sys.exit(0)

    if args.list:
        try:
            owned = fetch_owned_games(cfg.steam_api_key, steam_id)
        except Exception as e:
            log.warning("Не удалось получить имена игр: %s", e)
            owned = []
        log.info("Игр с trading cards к обработке: %d", len(games_with_drops))
        for appid, _ in games_with_drops:
            name = next(
                (g.get("name", "?") for g in owned if g["appid"] == appid), "?"
            )
            print(f"{appid:>10}  —  {name}")
        sys.exit(0)

    _farm_loop(games_with_drops, cfg, cookies, steam_id)


if __name__ == "__main__":
    main()
