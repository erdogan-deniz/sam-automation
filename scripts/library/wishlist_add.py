"""Auto-add Wishlist — добавляет позиции каталога Steam в вишлист аккаунта.

Добавляет только платное: бесплатное забирает в библиотеку add_free.py.
Без флагов типа — все типы. Флаги --games, --dlc, --software, --videos,
--hardware сужают выбор и складываются. Регистр флагов не важен (--DLC =
--dlc). Демо в вишлист не идут — их добавляет add_demos.py.

Две фазы: discover (GetAppList минус owned/wishlisted → candidates.txt) и add
(добавление по одному через IWishlistService, resume-aware, адаптивный
backoff на rate-limit). По умолчанию — dry-run (только discover + отчёт),
реальное добавление — только по --add.

Использование:
    python scripts/library/wishlist_add.py              # dry-run: сколько найдено
    python scripts/library/wishlist_add.py --add         # реально добавить
    python scripts/library/wishlist_add.py --add --dlc   # то же, только DLC
    python scripts/library/wishlist_add.py --add --games --software
    python scripts/library/wishlist_add.py --list        # показать candidates.txt
    python scripts/library/wishlist_add.py --add --limit 100
    python scripts/library/wishlist_add.py --add --retry-errors
    python scripts/library/wishlist_add.py --add --interval 0.2
    python scripts/library/wishlist_add.py --reset
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
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate
from app.wishlist import run
from app.wishlist import state as wishlist_state
from app.wishlist.content import ALL_TYPES, CONTENT_TYPES

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auto-add Wishlist — добавляет позиции каталога Steam в вишлист"
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="Реально добавить в вишлист (по умолчанию — dry-run, только discover)",
    )
    types = parser.add_argument_group(
        "типы контента (без флагов — все; флаги складываются)"
    )
    types.add_argument("--games", action="store_true", help="Игры")
    types.add_argument("--dlc", action="store_true", help="DLC")
    types.add_argument("--software", action="store_true", help="Софт")
    types.add_argument("--videos", action="store_true", help="Видео")
    types.add_argument("--hardware", action="store_true", help="Железо")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать кандидатов текущего режима и выйти",
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
        "--interval",
        type=float,
        default=1.0,
        help="Пауза между добавлениями в секундах (0 = максимальная скорость)",
    )
    return parser


def _selected_types(args: argparse.Namespace) -> frozenset[str]:
    """Типы из флагов; ни одного флага — все типы."""
    chosen = frozenset(t for t in CONTENT_TYPES if getattr(args, t))
    return chosen or ALL_TYPES


def main() -> None:
    args = _build_parser().parse_args(casefold_options(sys.argv[1:]))

    setup_logging(name="wishlist_add", category="library/wishlist_add")
    cfg = load_config()

    # Резолвим Steam ID ДО валидации — как add_free.py/scan.py/boost.py:
    # validate шлёт steam_id в GetPlayerSummaries, которому нужен числовой ID64.
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
            wishlist_state.clear_state()
            log.info("Сброшено resume-состояние (--reset)")
        if args.retry_errors:
            wishlist_state.clear_error_ids()
            log.info("Очищен error.txt (--retry-errors)")

    run(
        do_add=args.add,
        list_only=args.list,
        limit=args.limit,
        interval=args.interval,
        api_key=cfg.steam_api_key,
        steam_id=cfg.steam_id,
        cfg=cfg,
        types=_selected_types(args),
    )


if __name__ == "__main__":
    main()
