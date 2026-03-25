"""SAM Automation — автоматическая разблокировка всех достижений Steam.

Использование:
    python scripts/achievements/unlock.py              # полный автопилот
    python scripts/achievements/unlock.py --list       # только показать какие игры будут обработаны
    python scripts/achievements/unlock.py --reset      # сбросить прогресс и начать заново
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import time

from app.cache import (
    clear_error_ids,
    clear_progress,
    load_done_ids,
    load_error_ids,
    load_no_achievements_ids,
    mark_done,
    mark_error_id,
    mark_no_achievements,
)
from app.config import load_config
from app.exceptions import SAMError, SAMTooManyErrors
from app.validator import validate
from app.game_list import load_game_ids
from app.logging_setup import setup_logging
from app.safety import ErrorTracker
from app.sam import (
    check_steam_running,
    close_game,
    ensure_sam,
    kill_process,
    launch_picker,
    process_game,
)
from app.unlock_result import UnlockResult

log = logging.getLogger("sam_automation")


def _process_one_game(
    session,
    game_id: int,
    cfg,
    tracker: ErrorTracker,
    results: list[UnlockResult],
) -> bool:
    """Обрабатывает одну игру: открывает, разблокирует достижения, закрывает.

    Возвращает True если игра завершилась с ошибкой (SAMError или Exception).
    """
    game_app = None
    try:
        game_app = session.add_and_open_game(game_id, timeout=cfg.load_timeout)
        result = process_game(
            game_app,
            game_id,
            load_timeout=cfg.load_timeout,
            post_commit_delay=cfg.post_commit_delay,
        )
        results.append(result)
        tracker.record_success()

        if result.skipped:
            if result.skip_reason == "no achievements":
                mark_no_achievements(game_id)
            # skip_reason == "error" — временная ошибка SAM (таймаут, недоступно).
            # Не записываем в error_ids.txt — игра будет повторно обработана.
        else:
            mark_done(game_id)

        return False

    except SAMTooManyErrors:
        raise
    except SAMError as e:
        reason = e.message if hasattr(e, "message") else str(e)
        log.warning("[%d] STATUS: ERROR — %s", game_id, reason)
        tracker.record_error(game_id, e)
        results.append(
            UnlockResult(game_id=game_id, skipped=True, skip_reason=reason)
        )
        mark_error_id(game_id)
        return True
    except Exception as e:
        log.error("[%d] STATUS: ERROR — %s", game_id, e, exc_info=True)
        tracker.record_error(game_id, e)
        results.append(
            UnlockResult(game_id=game_id, skipped=True, skip_reason=str(e))
        )
        mark_error_id(game_id)
        return True
    finally:
        close_game(game_app)


def _apply_resume_filter(game_ids: list[int]) -> list[int]:
    """Исключает уже обработанные игры (done + error + no_achievements)."""
    skip = load_done_ids() | load_error_ids() | load_no_achievements_ids()
    if not skip:
        return game_ids
    before = len(game_ids)
    filtered = [gid for gid in game_ids if gid not in skip]
    skipped = before - len(filtered)
    if skipped:
        log.info(
            "Пропущено %d игр из done/error (--no-resume чтобы начать заново)",
            skipped,
        )
    return filtered


def _log_summary(results: list[UnlockResult], errors: int) -> None:
    """Выводит итоговую статистику в лог."""
    ok = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    log.info(
        "Разблокировано: %d | Пропущено: %d | Ошибок: %d",
        len(ok),
        len(skipped),
        errors,
    )
    for r in results:
        if not r.skipped:
            log.info("  %d: STATUS: UNLOCK +%d", r.game_id, r.newly_unlocked)
        elif r.skip_reason == "no achievements":
            log.info("  %d: STATUS: NO ACHIEVEMENTS", r.game_id)
        else:
            reason = f" — {r.skip_reason}" if r.skip_reason != "error" else ""
            log.info("  %d: STATUS: ERROR%s", r.game_id, reason)


def main() -> None:
    """Точка входа: парсит аргументы CLI и запускает цикл разблокировки достижений."""
    parser = argparse.ArgumentParser(description="SAM Automation")
    parser.add_argument(
        "--list", action="store_true", help="Показать список игр и выйти"
    )
    parser.add_argument(
        "--reset", action="store_true", help="Сбросить прогресс и начать заново"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Не пропускать уже обработанные игры",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Повторить только игры из error_ids.txt",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(
        verbose=args.verbose,
        name="unlock_achievements",
        category="achievements/unlock",
    )
    cfg = load_config()
    validate(cfg)

    if args.reset:
        clear_progress()
        log.info("Прогресс сброшен")

    if not check_steam_running():
        log.error("Steam не запущен! Запусти Steam и попробуй снова.")
        sys.exit(1)
    log.info("Steam запущен")

    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    if args.retry_errors:
        error_ids = sorted(load_error_ids())
        if not error_ids:
            log.info("Нет игр с ошибками для повтора.")
            sys.exit(0)
        log.info("Повтор %d игр из error_ids.txt", len(error_ids))
        clear_error_ids()
        game_ids = error_ids
    else:
        game_ids = load_game_ids(cfg)
        if not game_ids:
            log.info("Все достижения уже на 100%% — нечего обрабатывать!")
            sys.exit(0)

        if not args.no_resume:
            game_ids = _apply_resume_filter(game_ids)

    if not args.retry_errors and not game_ids:
        log.info(
            "Все игры уже обработаны! Используй --reset для повторного запуска."
        )
        sys.exit(0)

    if args.list:
        log.info("Игр для обработки: %d", len(game_ids))
        for gid in game_ids:
            print(gid)
        sys.exit(0)

    proc, session = launch_picker(
        cfg.sam_game_exe_path, launch_delay=cfg.launch_delay
    )

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
            if _process_one_game(session, game_id, cfg, tracker, results):
                errors += 1
            if i < total:
                time.sleep(cfg.between_games_delay)

    except SAMTooManyErrors:
        log.error("Прервано. Перезапусти скрипт — продолжит с места остановки.")
    except KeyboardInterrupt:
        log.info(
            "Прервано (Ctrl+C). Перезапусти — продолжит с места остановки."
        )
    finally:
        kill_process(proc)

    log.info("=" * 60)
    log.info("ИТОГИ")
    _log_summary(results, errors)


if __name__ == "__main__":
    main()
