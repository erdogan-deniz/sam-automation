"""Добавляет в библиотеку Steam весь бесплатный контент (B-19).

Две фазы: discover (весь каталог Steam: бесплатное и вышедшее, DLC — только к
играм из библиотеки → candidates.txt минус owned) и add (request_free_license
батчами, resume-aware). Типы контента — флаги --games, --dlc, --software,
--videos, --hardware (складываются; без флагов — все); демо — add_demos.py. По умолчанию — dry-run
(только discover + отчёт), реальное добавление лицензий — только по --add
(необратимое действие на аккаунте: добавленные бесплатные лицензии нельзя
удалить из библиотеки штатными средствами Steam).

Использование:
    python scripts/library/add_free_content.py              # dry-run: сколько найдено
    python scripts/library/add_free_content.py --add         # реально добавить
    python scripts/library/add_free_content.py --add --dlc   # только DLC к своим играм
    python scripts/library/add_free_content.py --list        # показать candidates.txt
    python scripts/library/add_free_content.py --add --limit 100
    python scripts/library/add_free_content.py --add --retry-errors
    python scripts/library/add_free_content.py --reset
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.cli import casefold_options
from app.config import load_config
from app.free_games import run
from app.free_games import state as free_games_state
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate
from app.wishlist.content import ALL_TYPES, CONTENT_TYPES

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Добавляет в библиотеку Steam весь бесплатный контент"
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="Реально добавить лицензии (по умолчанию — dry-run, только discover)",
    )
    types = parser.add_argument_group(
        "типы контента (без флагов — все; флаги складываются)"
    )
    types.add_argument("--games", action="store_true", help="Игры")
    types.add_argument(
        "--dlc", action="store_true", help="DLC к играм из библиотеки"
    )
    types.add_argument("--software", action="store_true", help="Софт")
    types.add_argument("--videos", action="store_true", help="Видео")
    types.add_argument("--hardware", action="store_true", help="Железо")
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
    return parser


def _selected_types(args: argparse.Namespace) -> frozenset[str]:
    """Типы из флагов; ни одного флага — все типы."""
    chosen = frozenset(t for t in CONTENT_TYPES if getattr(args, t))
    return chosen or ALL_TYPES


def main() -> None:
    args = _build_parser().parse_args(casefold_options(sys.argv[1:]))

    setup_logging(name="add_free_content", category="library/add_free_content")
    cfg = load_config()

    # Резолвим Steam ID (vanity-имя/URL → ID64) ДО валидации — как scan_library.py/
    # boost_playtime.py: validate шлёт steam_id в GetPlayerSummaries, которому нужен
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
        cfg=cfg,
        types=_selected_types(args),
    )


if __name__ == "__main__":
    main()
