"""Auto-add Free Games — добавляет бесплатные App ID в библиотеку Steam.

Две фазы: discover (витрина free store search → candidates.txt минус owned) и
add (request_free_license батчами, resume-aware). По умолчанию — dry-run
(только discover + отчёт), реальное добавление лицензий — только по --add
(необратимое действие на аккаунте: добавленные бесплатные лицензии нельзя
удалить из библиотеки штатными средствами Steam).

Использование:
    python scripts/library/add_free.py              # dry-run: сколько найдено
    python scripts/library/add_free.py --add         # реально добавить
    python scripts/library/add_free.py --list        # показать candidates.txt
    python scripts/library/add_free.py --add --limit 100
    python scripts/library/add_free.py --add --retry-errors
    python scripts/library/add_free.py --reset
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.config import load_config
from app.free_games import run
from app.free_games import state as free_games_state
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Auto-add Free Games — добавляет бесплатные игры/app в "
            "библиотеку Steam"
        )
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="Реально добавить лицензии (по умолчанию — dry-run, только discover)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать текущих кандидатов из candidates.txt и выйти",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить resume-состояние (candidates/added/refused/error)",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Повторить error.txt (транзиентные неудачи; НЕ refused — тот терминален)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Потолок числа добавлений за прогон",
    )
    parser.add_argument(
        "--no-demos",
        action="store_true",
        help="Пропустить демо-подфазу обнаружения",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    setup_logging(name="add_free", category="library/add_free")
    cfg = load_config()

    # Резолвим Steam ID (vanity-имя/URL → ID64) ДО валидации — как scan.py/
    # boost.py: validate шлёт steam_id в GetPlayerSummaries, которому нужен
    # числовой ID64. Пустой steam_id НЕ резолвим — пусть validate выдаст
    # локальную «missing».
    if cfg.steam_id:
        try:
            cfg.steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
        except (RuntimeError, KeyError) as e:
            log.error("Не удалось определить Steam ID: %s", e)
            sys.exit(1)

    validate(cfg)

    if args.list and (args.reset or args.retry_errors):
        log.warning(
            "--list только показывает кандидатов; --reset/--retry-errors "
            "игнорируются"
        )

    if not args.list:
        if args.reset:
            free_games_state.clear_state()
            log.info("Сброшено resume-состояние (--reset)")
        if args.retry_errors:
            free_games_state.clear_error_ids()
            log.info("Очищен error.txt (--retry-errors)")

    run(
        do_add=args.add,
        list_only=args.list,
        limit=args.limit,
        include_demos=not args.no_demos,
        cfg=cfg,
    )


if __name__ == "__main__":
    main()
