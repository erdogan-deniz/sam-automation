"""SAM Card Farming — автоматический фарм Steam trading card drops.

Открывает игры через SAM.Game.exe (создаёт фейковую игровую сессию).
Fast-mode цикл: идлит пачку игр, затем закрывает ВСЕ разом (аккаунт
выходит из in-game — Steam сбрасывает накопленные карты), выжидает
паузу, перечитывает остатки через Steam Community и запускает следующую
пачку. Игра с 0 остатком помечается done.

Использование:
    python scripts/cards/farm.py
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
from collections import deque
from typing import Any

from app.cache import load_game_names
from app.cards import (
    check_cards_remaining,
    clear_card_progress,
    fetch_games_with_card_drops,
    mark_card_done,
)
from app.config import load_config
from app.logging_setup import SEPARATOR, setup_logging
from app.notify import send_telegram, toast
from app.run_lock import acquire_run_lock, release_run_lock
from app.sam import (
    check_steam_running,
    ensure_sam,
    kill_all_sam_games,
    kill_process,
    launch_game,
)
from app.steam import get_web_cookies, resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")

_MAX_CHECK_FAILURES = (
    5  # после N неудачных проверок подряд считаем дропы закончившимися
)
_FLUSH_PAUSE_SECONDS = (
    20  # сек: после закрытия ВСЕХ игр аккаунт выходит из in-game —
    # даём Steam выдать накопленные карты (zero-transition flush)
)
_PAUSE_BETWEEN_GAMES = 3  # сек, пауза перед открытием следующей игры из очереди
_MAX_NO_PROGRESS = (
    10  # циклов без убывания остатка → считаем игру застрявшей и пропускаем
)


def _kill_game(appid: int, proc: subprocess.Popen) -> None:
    """Завершает SAM.Game.exe."""
    kill_process(proc)


def _open_next(
    queue: deque[tuple[int, int]],
    active: dict[int, subprocess.Popen],
    cfg: Any,
    game_names: dict,
    failed: list[int] | None = None,
) -> None:
    """Открывает следующую игру из очереди если есть место."""
    while queue and len(active) < cfg.max_concurrent_games:
        appid, cnt = queue.popleft()
        time.sleep(_PAUSE_BETWEEN_GAMES)
        try:
            proc = launch_game(cfg.sam_game_exe_path, appid)
        except RuntimeError as e:
            # Транзиентный сбой запуска (AV-локи, WinError) не должен рушить
            # весь прогон — пропускаем эту игру, не зацикливаясь на ней.
            log.warning("APP ID: %d — не удалось запустить: %s", appid, e)
            if failed is not None:
                failed.append(appid)
            continue
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
    """Fast-mode цикл фарма.

    Карта выдаётся сервером Steam в момент, когда аккаунт выходит из
    in-game состояния (закрыты ВСЕ игры). Поэтому цикл идлит пачку, затем
    убивает ВСЕ игры разом (коллапс в ноль), даёт паузу на сброс и только
    потом перечитывает остатки. Kill+relaunch по одной не работает: пока
    крутятся остальные, аккаунт всегда в игре и сброс не срабатывает.
    """
    queue: deque[tuple[int, int]] = deque(games_with_drops)
    active: dict[int, subprocess.Popen] = {}
    check_failures: dict[int, int] = {}
    last_remaining: dict[int, int] = {}  # для детекта застрявших игр
    no_progress: dict[int, int] = {}  # циклов подряд без убывания остатка
    stalled: list[int] = []  # брошены как застрявшие (остаток не убывал)
    unverified: list[int] = []  # брошены: не удалось определить остаток
    failed_launch: list[int] = []  # не удалось запустить SAM.Game.exe
    interrupted = False
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

    try:
        _open_next(queue, active, cfg, game_names, failed_launch)

        while active:
            log.info(
                "До следующей проверки осталось %d минут ...",
                cfg.card_check_interval,
            )
            log.info(SEPARATOR)
            time.sleep(cfg.card_check_interval * 60)

            # Коллапс в ноль: убиваем ВСЕ разом → аккаунт выходит из игры.
            log.info(
                "Закрываю все игры для сброса накопленных карт (%d шт.) ...",
                len(active),
            )
            batch = list(active.items())
            for appid, proc in batch:
                try:
                    _kill_game(appid, proc)
                except Exception:
                    log.warning(
                        "Не удалось закрыть APP ID %d при сбросе", appid
                    )
            active.clear()

            # Пауза на сброс: даём Steam выдать накопленные карты.
            time.sleep(_FLUSH_PAUSE_SECONDS)

            # Перечитываем остатки по каждой закрытой игре.
            cookie_refresh_tried = False
            for appid, _proc in batch:
                remaining = check_cards_remaining(cookies, steam_id, appid)
                if remaining < 0 and not cookie_refresh_tried:
                    # Пачка -1 часто = протухли web-куки, а не «нет карт».
                    # Обновляем НЕинтерактивно раз за батч и перечитываем,
                    # чтобы не помечать игры unverified из-за истёкшей сессии.
                    cookie_refresh_tried = True
                    fresh = get_web_cookies(cfg.steam_id, interactive=False)
                    if fresh:
                        cookies = fresh
                        log.info(
                            "APP ID: %d — остаток -1; обновил web-куки, "
                            "перечитываю",
                            appid,
                        )
                        remaining = check_cards_remaining(
                            cookies, steam_id, appid
                        )
                time.sleep(1.0)  # пауза между запросами

                if remaining == 0:
                    log.info("APP ID: %d — Card drops закончились", appid)
                    check_failures.pop(appid, None)
                    no_progress.pop(appid, None)
                    last_remaining.pop(appid, None)
                    mark_card_done(appid)
                elif remaining > 0:
                    prev = last_remaining.get(appid)
                    if prev is not None and remaining >= prev:
                        stalls = no_progress.get(appid, 0) + 1
                        if stalls >= _MAX_NO_PROGRESS:
                            log.warning(
                                "APP ID: %d — остаток не убывает %d циклов, "
                                "бросаю (НЕ помечаю done — дропы не идут)",
                                appid,
                                stalls,
                            )
                            no_progress.pop(appid, None)
                            last_remaining.pop(appid, None)
                            check_failures.pop(appid, None)
                            stalled.append(appid)
                            continue
                        no_progress[appid] = stalls
                    else:
                        no_progress.pop(appid, None)
                    last_remaining[appid] = remaining
                    check_failures[appid] = 0
                    queue.append((appid, remaining))
                else:
                    failures = check_failures.get(appid, 0) + 1
                    check_failures[appid] = failures
                    if failures >= _MAX_CHECK_FAILURES:
                        log.warning(
                            "APP ID: %d — не удалось определить остаток за %d "
                            "проверок, бросаю (НЕ помечаю done)",
                            appid,
                            failures,
                        )
                        check_failures.pop(appid, None)
                        no_progress.pop(appid, None)
                        last_remaining.pop(appid, None)
                        unverified.append(appid)
                    else:
                        queue.append((appid, remaining))

            # Перезапуск следующей пачки из очереди (включая выживших).
            _open_next(queue, active, cfg, game_names, failed_launch)

    except KeyboardInterrupt:
        interrupted = True
        log.info("Прервано (Ctrl+C). Закрываю все активные игры...")
    finally:
        for appid, proc in list(active.items()):
            try:
                _kill_game(appid, proc)
            except Exception:
                log.warning(
                    "Не удалось закрыть APP ID %d при завершении", appid
                )
        # Страховка: добиваем любые оставшиеся SAM.Game.exe (напр. процесс,
        # запущенный, но ещё не попавший в active при Ctrl+C). run-lock исключает
        # другой НАШ скрипт, но НЕ вручную запущенный SAM (тоже будет убит).
        kill_all_sam_games()

    log.info(SEPARATOR)
    if interrupted:
        log.warning("Card farming ПРЕРВАН — обработаны не все игры")
        log.info(SEPARATOR)
        toast("SAM Automation — Cards", "Card farming прерван")
        send_telegram("⚠️ Card farming прерван — обработаны не все игры", cfg)
    elif failed_launch or stalled or unverified:
        log.warning(
            "Card farming завершён С ОГОВОРКАМИ: не запущено %d, застряло %d, "
            "не проверено %d (НЕ помечены done, переоткроются в след. прогоне)",
            len(failed_launch),
            len(stalled),
            len(unverified),
        )
        log.info(SEPARATOR)
        toast(
            "SAM Automation — Cards",
            f"С оговорками: не запущено {len(failed_launch)}, "
            f"застряло {len(stalled)}, не проверено {len(unverified)}",
        )
        send_telegram(
            f"⚠️ Card farming с оговорками: не запущено {len(failed_launch)}, "
            f"застряло {len(stalled)}, не проверено {len(unverified)}",
            cfg,
        )
    else:
        log.info("Card farming завершён")
        log.info(SEPARATOR)
        toast("SAM Automation — Cards", "Card farming завершён")
        send_telegram("✅ Card farming завершён", cfg)


def _build_parser() -> argparse.ArgumentParser:
    """CLI-флаги card farming."""
    parser = argparse.ArgumentParser(
        description="SAM Card Farming — фарм Steam trading card drops"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить прогресс (cards/done.txt) и начать заново",
    )
    return parser


def _prepare_progress(args: argparse.Namespace) -> None:
    """Применяет флаг сброса прогресса до начала фарма."""
    if args.reset:
        clear_card_progress()
        log.info("Сброшен прогресс card farming (--reset)")


def main() -> None:
    """Точка входа: запускает цикл фарма trading cards."""
    print()
    args = _build_parser().parse_args()
    setup_logging(name="farm_cards", category="cards/farm")
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
    _prepare_progress(args)

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
