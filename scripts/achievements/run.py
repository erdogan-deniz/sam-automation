"""SAM Automation — сканирование библиотеки + разблокировка достижений.

Объединяет scan.py и farm.py в один скрипт:
  1. Сканирует библиотеку Steam (VDF, API, CM) → ids.txt
  2. Запускает разблокировку достижений через SAM

Использование:
    python scripts/achievements/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import logging
import os
import time

# Должно быть до любого импорта protobuf (используется steam библиотекой)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.cache import (
    ALL_IDS_FILE,
    load_done_ids,
    load_error_ids,
    load_game_names,
    load_no_achievements_ids,
    mark_done,
    mark_error_id,
    mark_no_achievements,
    save_game_names,
)
from app.config import load_config
from app.exceptions import SAMError, SAMTooManyErrors
from app.game_list import load_game_ids
from app.id_file import read_ids_ordered
from app.logging_setup import setup_logging
from app.notify import toast
from app.safety import ErrorTracker
from app.sam import (
    check_steam_running,
    close_game,
    ensure_sam,
    kill_process,
    launch_picker,
    process_game,
)
from app.steam import find_steam_path, read_library_app_ids
from app.unlock_result import UnlockResult
from app.validator import validate

log = logging.getLogger("sam_automation")


# ── Scan ─────────────────────────────────────────────────────────────────────


def _read_vdf_ids(steam_path: str | None, steam_id: str) -> list[int]:
    """Читает App ID из localconfig.vdf (локальная история запуска игр)."""
    if not steam_path:
        log.warning("Папка Steam не найдена. Укажи steam_path в config.yaml")
        return []
    try:
        return read_library_app_ids(steam_path, steam_id)
    except Exception as e:
        log.warning("localconfig.vdf: %s", e)
        return []


def _read_api_ids(api_key: str | None, steam_id: str) -> list[int]:
    """Читает App ID из Steam API, сохраняет имена игр."""
    if not api_key:
        log.info("steam_api_key не задан — пропускаю Steam API")
        return []

    log.info("Получение ID приложений библиотеки Steam через Steam API")

    try:
        from app.steam import fetch_owned_games

        games = fetch_owned_games(api_key, steam_id)
        names = {g["appid"]: g["name"] for g in games if g.get("name")}
        if names:
            save_game_names(names)
            log.info("Сохранено имён игр: %d", len(names))
        return [g["appid"] for g in games]
    except Exception as e:
        log.warning("Steam API: %s", e)
        return []


def _read_cm_ids(steam_path: str | None) -> list[int]:
    """Читает App ID через Steam CM (все лицензии аккаунта)."""
    if not steam_path:
        return []
    try:
        from app.steam import read_steam_cm_app_ids

        return read_steam_cm_app_ids(steam_path, "", interactive=True)
    except KeyboardInterrupt:
        log.info("Steam CM: отменено пользователем")
        return []
    except Exception as e:
        log.warning("Steam CM: %s", e)
        return []


def _scan(cfg, steam_path: str | None) -> bool:
    """Сканирует библиотеку Steam и записывает ids.txt.

    Возвращает True если найдены ID, False если нет.
    """
    log.info("Сканирование приложений библиотеки Steam")
    log.info("═" * 80)
    log.info("Ваш Steam ID: %s", cfg.steam_id)

    prev_ids = (
        set(read_ids_ordered(ALL_IDS_FILE)) if ALL_IDS_FILE.exists() else set()
    )

    combined: list[int] = []
    seen: set[int] = set()

    def _merge(new_ids: list[int]) -> None:
        for gid in new_ids:
            if gid not in seen:
                seen.add(gid)
                combined.append(gid)

    log.info("═" * 80)
    _merge(_read_vdf_ids(steam_path, cfg.steam_id))
    new_before_cm = sum(1 for gid in combined if gid not in prev_ids)
    log.info(
        "Найдено %d новых ID приложений библиотеки Steam из локального файла",
        new_before_cm,
    )

    log.info("═" * 80)
    _merge(_read_api_ids(cfg.steam_api_key, cfg.steam_id))
    new_after_api = sum(1 for gid in combined if gid not in prev_ids)
    log.info(
        "Найдено %d новых ID приложений библиотеки Steam через Steam API",
        new_after_api - new_before_cm,
    )

    log.info("═" * 80)
    cm_ids = _read_cm_ids(steam_path)
    cm_new = sum(1 for gid in cm_ids if gid not in prev_ids)
    _merge(cm_ids)

    new_count = sum(1 for gid in combined if gid not in prev_ids)
    log.info(
        "Найдено %d новых ID приложений библиотеки Steam через Steam Client Master",
        cm_new,
    )

    if not combined:
        log.error("Ни один источник не вернул ID. Проверь steam_id и конфиг.")
        return False

    log.info("═" * 80)
    log.info("Итого: найдено %d ID приложений библиотеки Steam", len(combined))
    log.info(
        "Итого: найдено %d новых ID приложений библиотеки Steam",
        new_count,
    )

    ALL_IDS_FILE.parent.mkdir(exist_ok=True)
    ALL_IDS_FILE.write_text(
        "\n".join(str(i) for i in sorted(combined)) + "\n", encoding="utf-8"
    )
    log.info("Записано в: %s", ALL_IDS_FILE)
    return True


# ── Farm ─────────────────────────────────────────────────────────────────────


def _process_one_game(
    session,
    game_id: int,
    cfg,
    tracker: ErrorTracker,
    results: list[UnlockResult],
    name: str = "",
) -> bool:
    """Обрабатывает одну игру. Возвращает True при ошибке."""
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
        tracker.record_success()

        if result.skipped:
            if result.skip_reason == "no achievements":
                mark_no_achievements(game_id)
            else:
                mark_error_id(game_id)
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
    """Выводит итоговую статистику."""
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


def _farm(cfg) -> None:
    """Запускает цикл разблокировки достижений."""
    game_ids = load_game_ids(cfg)
    if not game_ids:
        if not ALL_IDS_FILE.exists() and not cfg.game_ids_file and not cfg.game_ids:
            log.error("ids.txt не найден и сканирование не дало результатов")
            sys.exit(1)
        log.info("Список игр пуст (все исключены конфигом?)")
        return

    game_ids = _apply_resume_filter(game_ids)

    if not game_ids:
        done = len(load_done_ids())
        no_ach = len(load_no_achievements_ids())
        errors = len(load_error_ids())
        log.info(
            "Все игры обработаны — done: %d, no achievements: %d, errors: %d",
            done, no_ach, errors,
        )
        return

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

    try:
        for i, game_id in enumerate(game_ids, 1):
            name = game_names.get(game_id, "")
            header = f"[{i}/{total}]"
            side = (70 - len(header) - 2) // 2
            log.info("%s %s %s", "═" * side, header, "═" * side)
            log.info("APP ID: %d", game_id)
            if _process_one_game(session, game_id, cfg, tracker, results, name):
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

    print()
    log.info("═" * 80)
    log.info("ИТОГИ")
    _log_summary(results, errors)

    ok = sum(1 for r in results if not r.skipped)
    toast(
        "SAM Automation — Achievements",
        f"Готово: {ok} разблокировано, {errors} ошибок из {total} игр",
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    """Сканирование библиотеки + разблокировка достижений."""
    print()
    setup_logging(
        verbose=False,
        name="achievements",
        category="achievements/run",
    )
    log.info("SAM Automation: Achievements")
    log.info("═" * 80)
    cfg = load_config()
    validate(cfg)

    if not check_steam_running():
        log.error("Steam клиент не запущен")
        sys.exit(1)
    log.info("Steam клиент запущен")

    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    steam_path = cfg.steam_path or find_steam_path()

    # Фаза 1: сканирование
    log.info("═" * 80)
    log.info("ФАЗА 1: Сканирование библиотеки Steam")
    log.info("═" * 80)
    _scan(cfg, steam_path)

    # Фаза 2: разблокировка достижений
    log.info("═" * 80)
    log.info("ФАЗА 2: Разблокировка достижений")
    log.info("═" * 80)

    _farm(cfg)


if __name__ == "__main__":
    main()
