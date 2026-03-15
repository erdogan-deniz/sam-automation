"""SAM Automation — автоматическая разблокировка всех достижений Steam.

Использование:
    python main.py              # полный автопилот
    python main.py --list       # только показать какие игры будут обработаны
    python main.py --reset      # сбросить прогресс и начать заново
"""

from __future__ import annotations

import argparse
import sys
import time
import logging

from sam_automation.cache import (
    clear_progress, load_done_ids, load_error_ids, load_no_achievements_ids,
    mark_done, mark_error_id, mark_no_achievements,
)
from sam_automation.config import load_config
from sam_automation.exceptions import SAMError, SAMTooManyErrors
from sam_automation.game_list import load_game_ids
from sam_automation.launcher import close_game, kill_process, launch_picker
from sam_automation.logging_setup import setup_logging
from sam_automation.manager_window import UnlockResult, process_game
from sam_automation.safety import ErrorTracker
from sam_automation.setup import check_steam_running, ensure_sam


def main():
    parser = argparse.ArgumentParser(description="SAM Automation")
    parser.add_argument("--list", action="store_true", help="Показать список игр и выйти")
    parser.add_argument("--reset", action="store_true", help="Сбросить прогресс и начать заново")
    parser.add_argument("--no-resume", action="store_true", help="Не пропускать уже обработанные игры")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log = setup_logging(verbose=args.verbose, name="unlock")
    cfg = load_config()

    if args.reset:
        clear_progress()
        log.info("Прогресс сброшен")

    # Валидация
    if not cfg.steam_api_key or not cfg.steam_id:
        log.error("Заполни steam_api_key и steam_id в config.yaml")
        log.error("API ключ: https://steamcommunity.com/dev/apikey")
        sys.exit(1)

    # Проверяем Steam
    if not check_steam_running():
        log.error("Steam не запущен! Запусти Steam и попробуй снова.")
        sys.exit(1)
    log.info("Steam запущен")

    # Авто-скачивание SAM если нет
    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    # Получаем список игр
    game_ids = load_game_ids(cfg)

    if not game_ids:
        log.info("Все достижения уже на 100%% — нечего обрабатывать!")
        sys.exit(0)

    # Фильтруем уже обработанные (resume)
    if not args.no_resume:
        skip = load_done_ids() | load_error_ids() | load_no_achievements_ids()
        if skip:
            before = len(game_ids)
            game_ids = [gid for gid in game_ids if gid not in skip]
            skipped = before - len(game_ids)
            if skipped:
                log.info("Пропущено %d игр из done/error (--no-resume чтобы начать заново)", skipped)

    if not game_ids:
        log.info("Все игры уже обработаны! Используй --reset для повторного запуска.")
        sys.exit(0)

    if args.list:
        log.info("Игр для обработки: %d", len(game_ids))
        for gid in game_ids:
            print(gid)
        sys.exit(0)

    # Запускаем SAM.Picker.exe — session кэширует окно и элементы на весь процесс
    log.info("Запуск SAM.Picker.exe ...")
    proc, session = launch_picker(cfg.sam_game_exe_path, launch_delay=cfg.launch_delay)

    total = len(game_ids)
    log.info("=" * 60)
    log.info("SAM Automation — начало работы")
    log.info("Игр к обработке: %d", total)
    log.info("=" * 60)

    tracker = ErrorTracker(max_consecutive=cfg.max_consecutive_errors)
    results: list[UnlockResult] = []
    errors = 0

    try:
        for i, game_id in enumerate(game_ids, 1):
            log.info("[%d/%d] Игра: %d", i, total, game_id)

            game_app = None
            try:
                game_app = session.add_and_open_game(game_id, timeout=cfg.load_timeout)

                result = process_game(
                    game_app, game_id,
                    load_timeout=cfg.load_timeout,
                    post_commit_delay=cfg.post_commit_delay,
                )
                results.append(result)
                tracker.record_success()

                if result.skipped and result.skip_reason == "no achievements":
                    mark_no_achievements(game_id)
                else:
                    mark_done(game_id)

            except SAMTooManyErrors:
                log.error("Аварийная остановка: слишком много ошибок подряд!")
                raise
            except (SAMError, Exception) as e:
                errors += 1
                if not isinstance(e, SAMError):
                    log.error("[%d] Ошибка: %s", game_id, e, exc_info=True)
                tracker.record_error(game_id, e)
                results.append(UnlockResult(game_id=game_id, skipped=True, skip_reason=str(e)))
                mark_error_id(game_id)
            finally:
                # Закрываем SAM.Game напрямую — не трогаем Picker
                close_game(game_app)

                if i < total:
                    time.sleep(cfg.between_games_delay)

    except SAMTooManyErrors:
        log.error("Прервано. Перезапусти скрипт — продолжит с места остановки.")
    except KeyboardInterrupt:
        log.info("Прервано (Ctrl+C). Перезапусти — продолжит с места остановки.")
    finally:
        kill_process(proc)

    # Итоги
    log.info("=" * 60)
    log.info("ИТОГИ")
    ok = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    log.info("Разблокировано: %d | Пропущено: %d | Ошибок: %d", len(ok), len(skipped), errors)
    for r in results:
        status = "OK" if not r.skipped else "ПРОПУСК"
        detail = f"+{r.newly_unlocked}" if not r.skipped else r.skip_reason
        log.info("  %d: %s — %s", r.game_id, status, detail)


if __name__ == "__main__":
    main()
