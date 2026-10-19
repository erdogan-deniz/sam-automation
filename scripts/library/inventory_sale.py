"""Распродажа инвентаря Steam — продать по рынку или разобрать на самоцветы (B-16).

Каждый продаваемый предмет (кроме карточек недособранных значков и бустер-паков)
либо выставляется на маркет, либо разбирается на самоцветы — что выгоднее.
Есть заявка на покупку: на руки по заявке против самоцветов; заявок нет —
выставляется по самой низкой цене продажи и висит. По умолчанию — dry-run (только
план и суммы); реальные действия — по --sell и --grind. Лоты подтверждаются в
мобильном Steam Guard вручную. Регистр флагов не важен.

Использование:
    python scripts/library/inventory_sale.py                 # план и суммы
    python scripts/library/inventory_sale.py --list          # таблица по предметам
    python scripts/library/inventory_sale.py --sell          # выставить лоты
    python scripts/library/inventory_sale.py --grind         # разобрать на самоцветы
    python scripts/library/inventory_sale.py --sell --grind --limit 20
    python scripts/library/inventory_sale.py --reset         # забыть сделанное
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
from app.inventory.run import run
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Распродажа инвентаря Steam: продать или разобрать на самоцветы"
    )
    parser.add_argument(
        "--sell",
        action="store_true",
        help="Выставить лоты (по умолчанию — dry-run, только план)",
    )
    parser.add_argument(
        "--grind",
        action="store_true",
        help="Разобрать на самоцветы (необратимо)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать план по каждому предмету и выйти",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Потолок числа операций (выставлений и разборов) за прогон",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Пауза между операциями в секундах (маркет быстро отдаёт 429)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Забыть сделанное (например, после снятия лотов) и выйти",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args(casefold_options(sys.argv[1:]))

    setup_logging(name="inventory_sale", category="library/inventory_sale")
    cfg = load_config()

    # Steam ID64 нужен инвентарю, GetBadges и URL профиля.
    if cfg.steam_id:
        try:
            cfg.steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
        except (RuntimeError, KeyError) as e:
            log.error("Не удалось определить Steam ID: %s", e)
            sys.exit(1)

    validate(cfg)

    run(
        do_sell=args.sell,
        do_grind=args.grind,
        list_only=args.list,
        limit=args.limit,
        interval=args.interval,
        reset=args.reset,
        steam_id=cfg.steam_id,
        cfg=cfg,
    )


if __name__ == "__main__":
    main()
