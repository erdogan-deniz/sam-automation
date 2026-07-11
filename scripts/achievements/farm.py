"""SAM Automation — автоматическая разблокировка всех достижений Steam.

Использование:
    python scripts/achievements/farm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import atexit
import logging
import time

from app.cache import (
    clear_error_ids,
    clear_progress,
    load_done_ids,
    load_error_ids,
    load_game_names,
    load_no_achievements_ids,
    mark_done,
    mark_error_id,
    mark_no_achievements,
)
from app.catalog import load_with_ids, prioritize_by_with
from app.config import load_config
from app.exceptions import SAMError, SAMTooManyErrors
from app.game_list import load_game_ids
from app.logging_setup import SEPARATOR, centered, setup_logging
from app.notify import send_telegram, toast
from app.run_lock import acquire_run_lock, release_run_lock
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
from app.validator import validate

log = logging.getLogger("sam_automation")


def _process_one_game(
    session,
    game_id: int,
    cfg,
    tracker: ErrorTracker,
    results: list[UnlockResult],
    name: str = "",
) -> bool:
    """Обрабатывает одну игру: открывает, разблокирует достижения, закрывает.

    Возвращает True если игра завершилась с ошибкой (SAMError или Exception).
    """
    game_app = None
    try:
        game_app = session.add_and_open_game(game_id, timeout=cfg.load_timeout)
        if name:
            log.info("APP NAME: %s", name)
        result = process_game(
            game_app,
            game_id,
            load_timeout=cfg.load_timeout,
            post_commit_delay=cfg.post_commit_delay,
        )
        results.append(result)

        # Мягкая ошибка загрузки (skip_reason="error"/"retry") — НЕ исключение,
        # но реальный провал: считаем ошибкой, иначе прогон, где все игры не
        # загрузились (Steam offline / global user / протухшие куки), ложно
        # рапортует ✅. record_success — только на честном исходе (UNLOCK / нет
        # достижений), чтобы серия таких ошибок взводила аварийный стоп.
        if result.skipped and result.skip_reason not in ("", "no achievements"):
            tracker.record_error(game_id, SAMError(result.skip_reason))
            mark_error_id(game_id)
            return True

        tracker.record_success()
        if result.skipped:  # skip_reason == "no achievements"
            mark_no_achievements(game_id)
        else:
            mark_done(game_id)
        return False

    except SAMTooManyErrors:
        raise
    except SAMError as e:
        reason = e.message if hasattr(e, "message") else str(e)
        log.warning("APP STATUS: ERROR — %s", reason)
        tracker.record_error(game_id, e)
        results.append(
            UnlockResult(game_id=game_id, skipped=True, skip_reason=reason)
        )
        mark_error_id(game_id)
        return True
    except Exception as e:
        log.error("APP STATUS: ERROR — %s", e, exc_info=True)
        tracker.record_error(game_id, e)
        results.append(
            UnlockResult(game_id=game_id, skipped=True, skip_reason=str(e))
        )
        mark_error_id(game_id)
        return True
    finally:
        close_game(game_app)


def _build_parser() -> argparse.ArgumentParser:
    """CLI-флаги farm: сброс прогресса и отключение резюма."""
    parser = argparse.ArgumentParser(
        description="Разблокировка достижений Steam через SAM"
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Очистить error.txt — повторить игры, завершившиеся ошибкой",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить весь прогресс (done/error/without) и начать заново",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Обработать все игры, игнорируя сохранённый прогресс этим прогоном",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _prepare_progress(args: argparse.Namespace) -> None:
    """Применяет флаги сброса прогресса до построения списка игр."""
    if args.reset:
        clear_progress()
        log.info("Сброшен весь прогресс (--reset)")
    elif args.retry_errors:
        clear_error_ids()
        log.info(
            "Очищен список ошибок — игры из error будут повторены "
            "(--retry-errors)"
        )


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
            log.info("  %d: STATUS: UNLOCK (+%d)", r.game_id, r.newly_unlocked)
        elif r.skip_reason == "no achievements":
            log.info("  %d: STATUS: NO ACHIEVEMENTS", r.game_id)
        else:
            reason = f" — {r.skip_reason}" if r.skip_reason != "error" else ""
            log.info("  %d: STATUS: ERROR%s", r.game_id, reason)


def _report_result(
    status: str, unlocked: int, errors: int, total: int, cfg
) -> None:
    """Честный финальный отчёт (лог + toast + Telegram).

    success-«✅ готово» только когда прогон дошёл до конца без ошибок. Ctrl+C
    (`interrupted`), аварийный стоп по серии ошибок (`aborted`) и наличие
    ошибок дают ⚠️ и честный текст — инвариант честного отчёта.
    """
    if status == "interrupted":
        head, ok = "прервано (Ctrl+C)", False
    elif status == "aborted":
        head, ok = "прервано (слишком много ошибок)", False
    elif errors:
        head, ok = "готово с оговорками", False
    else:
        head, ok = "готово", True
    detail = f"разблокировано {unlocked}, ошибок {errors} из {total} игр"
    log.info(SEPARATOR)
    log.info("Achievements — %s. %s", head, detail)
    log.info(SEPARATOR)
    toast("SAM Automation — Achievements", f"{head}: {detail}")
    mark = "✅" if ok else "⚠️"
    send_telegram(f"{mark} Achievements — {head}: {detail}", cfg)


def main() -> None:
    """Точка входа: запускает цикл разблокировки достижений."""
    print()
    args = _build_parser().parse_args()
    setup_logging(
        verbose=args.verbose,
        name="farm_achievements",
        category="achievements/farm",
    )
    try:
        acquire_run_lock("achievements/farm")
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)
    atexit.register(release_run_lock)
    log.info("Разблокировка достижений Steam")
    log.info(SEPARATOR)
    cfg = load_config()
    validate(cfg)
    _prepare_progress(args)

    if not check_steam_running():
        log.error("Steam клиент не запущен")
        sys.exit(1)
    log.info("Steam клиент запущен")

    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    game_ids = load_game_ids(cfg)
    if not game_ids:
        from app.cache import ALL_IDS_FILE

        if (
            not ALL_IDS_FILE.exists()
            and not cfg.game_ids_file
            and not cfg.game_ids
        ):
            log.error(
                "all.txt не найден — запусти scan.py для формирования списка игр"
            )
            sys.exit(1)
        log.info("Список игр пуст (все исключены конфигом?)")
        sys.exit(0)

    if not args.no_resume:
        game_ids = _apply_resume_filter(game_ids)

    # Advisory-приоритет: игры с подтверждёнными достижениями (with.txt) —
    # вперёд. Состав списка не меняется, только порядок.
    catalog_with = load_with_ids()
    game_ids = prioritize_by_with(game_ids, catalog_with)
    n_priority = len(set(game_ids) & catalog_with)
    if n_priority:
        log.info(
            "Каталог: %d игр с достижениями обрабатываются первыми", n_priority
        )

    if not game_ids:
        done = len(load_done_ids())
        no_ach = len(load_no_achievements_ids())
        errors = len(load_error_ids())
        log.info(
            "Все игры обработаны — done: %d, no achievements: %d, errors: %d",
            done,
            no_ach,
            errors,
        )
        sys.exit(0)

    proc, session = launch_picker(
        cfg.sam_game_exe_path, launch_delay=cfg.launch_delay
    )

    game_names = load_game_names()
    total = len(game_ids)
    log.info("Игр к обработке: %d", total)
    print()

    tracker = ErrorTracker(max_consecutive=cfg.max_consecutive_errors)
    results: list[UnlockResult] = []
    errors = 0
    status = "ok"

    try:
        for i, game_id in enumerate(game_ids, 1):
            name = game_names.get(game_id, "")
            header = f"[{i}/{total}]"
            log.info(centered(header))
            log.info("APP ID: %d", game_id)
            if _process_one_game(session, game_id, cfg, tracker, results, name):
                errors += 1
            if i < total:
                time.sleep(cfg.between_games_delay)

    except SAMTooManyErrors:
        status = "aborted"
        log.error("Прервано. Перезапусти скрипт — продолжит с места остановки.")
    except KeyboardInterrupt:
        status = "interrupted"
        log.info(
            "Прервано (Ctrl+C). Перезапусти — продолжит с места остановки."
        )
    finally:
        kill_process(proc)

    print()
    log.info(SEPARATOR)
    log.info("ИТОГИ")
    _log_summary(results, errors)

    unlocked = sum(1 for r in results if not r.skipped)
    _report_result(status, unlocked, errors, total, cfg)


if __name__ == "__main__":
    main()
