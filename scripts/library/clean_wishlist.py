"""Чистка Wishlist — удаляет из вишлиста бесплатное и не вышедшее (B-17/B-18).

В вишлисте должно лежать только платное и вышедшее: бесплатное забирает в
библиотеку add_free_games.py, не вышедшее fill_wishlist.py добавит, когда оно выйдет.
По умолчанию — dry-run (только подсчёт), реальное удаление — только по
--remove. Регистр флагов не важен.

Использование:
    python scripts/library/clean_wishlist.py                # сколько удалить
    python scripts/library/clean_wishlist.py --remove       # реально удалить
    python scripts/library/clean_wishlist.py --free         # только бесплатное
    python scripts/library/clean_wishlist.py --unreleased   # только не вышедшее
    python scripts/library/clean_wishlist.py --list         # показать список
    python scripts/library/clean_wishlist.py --remove --limit 100
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
from app.wishlist.clean import ALL_REASONS, REASONS, run

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Чистка Wishlist — удаляет бесплатное и не вышедшее"
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Реально удалить (по умолчанию — dry-run, только подсчёт)",
    )
    reasons = parser.add_argument_group(
        "что удалять (без флагов — всё; флаги складываются)"
    )
    reasons.add_argument("--free", action="store_true", help="Бесплатное")
    reasons.add_argument(
        "--unreleased", action="store_true", help="Не вышедшее"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать кандидатов на удаление и выйти",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Потолок числа удалений за прогон",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Пауза между удалениями в секундах (0 = максимальная скорость)",
    )
    return parser


def _selected_reasons(args: argparse.Namespace) -> frozenset[str]:
    """Причины из флагов; ни одного флага — все."""
    chosen = frozenset(r for r in REASONS if getattr(args, r))
    return chosen or ALL_REASONS


def main() -> None:
    args = _build_parser().parse_args(casefold_options(sys.argv[1:]))

    setup_logging(name="clean_wishlist", category="library/clean_wishlist")
    cfg = load_config()

    # Steam ID резолвим ДО валидации, как fill_wishlist.py: GetWishlist и
    # GetPlayerSummaries нужен числовой ID64.
    if cfg.steam_id:
        try:
            cfg.steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
        except (RuntimeError, KeyError) as e:
            log.error("Не удалось определить Steam ID: %s", e)
            sys.exit(1)

    validate(cfg)

    run(
        do_remove=args.remove,
        list_only=args.list,
        limit=args.limit,
        interval=args.interval,
        steam_id=cfg.steam_id,
        cfg=cfg,
        reasons=_selected_reasons(args),
    )


if __name__ == "__main__":
    main()
