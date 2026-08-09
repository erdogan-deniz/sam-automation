"""Auto-add Wishlist — добавляет позиции каталога Steam в вишлист аккаунта.

Две фазы: discover (GetAppList минус owned/wishlisted → candidates.txt) и add
(добавление по одному через IWishlistService, resume-aware, адаптивный
backoff на rate-limit). По умолчанию — dry-run (только discover + отчёт),
реальное добавление — только по --add.

Использование:
    python scripts/library/wishlist_add.py              # dry-run: сколько найдено
    python scripts/library/wishlist_add.py --add         # реально добавить
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

from app.config import load_config
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate
from app.wishlist import run
from app.wishlist import state as wishlist_state

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
        "--interval",
        type=float,
        default=1.0,
        help="Пауза между добавлениями в секундах (0 = максимальная скорость)",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

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
    )


if __name__ == "__main__":
    main()
