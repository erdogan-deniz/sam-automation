"""Advisory-каталог достижений: раскладка библиотеки через Store API.

Классифицирует игры из all.txt на with.txt (Store подтвердил достижения) и
store_zero.txt (Store сказал 0 — СОВЕТ, farm это НЕ пропускает). Кэшируется и
возобновляется: уже классифицированные пропускаются; unknown (Store недоступен)
перезапрашивается в следующий прогон. Только SAM/farm метит «без достижений»
терминально — этот каталог на farm не влияет.

Store API ~1.2с/запрос, полная библиотека — часы. Используй --limit для частей.

Использование:
    python scripts/categorize.py              # классифицировать остаток
    python scripts/categorize.py --limit 500  # не более 500 запросов за прогон
    python scripts/categorize.py --reset      # начать каталог заново
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging  # noqa: E402

from app.cache import ALL_IDS_FILE  # noqa: E402
from app.catalog import (  # noqa: E402
    classify_achievements,
    clear_catalog,
    load_store_empty_ids,
    load_store_zero_ids,
    load_with_ids,
    mark_store_empty,
    mark_store_zero,
    mark_with,
    remaining_to_classify,
)
from app.id_file import load_ids_file  # noqa: E402
from app.logging_setup import SEPARATOR, setup_logging  # noqa: E402
from app.steam.store_api import fetch_achievement_info  # noqa: E402

log = logging.getLogger("sam_automation")

_REQUEST_DELAY = 1.2  # секунд между запросами (Store API rate limit)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Advisory-каталог достижений (Store API)"
    )
    parser.add_argument(
        "--reset", action="store_true", help="очистить каталог и начать заново"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="макс. запросов к Store за прогон (0 = все оставшиеся)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    setup_logging(name="categorize", category="achievements/scan")

    if args.reset:
        clear_catalog()
        log.info("Каталог сброшен")

    all_ids = load_ids_file(ALL_IDS_FILE)
    remaining = remaining_to_classify(
        all_ids,
        load_with_ids(),
        load_store_zero_ids(),
        load_store_empty_ids(),
    )
    if args.limit > 0:
        remaining = remaining[: args.limit]

    log.info(SEPARATOR)
    log.info(
        "Каталогизация: %d игр (из %d в библиотеке)",
        len(remaining),
        len(all_ids),
    )
    log.info(SEPARATOR)

    with_n = zero_n = empty_n = unknown_n = 0
    total = len(remaining)
    for i, appid in enumerate(remaining, 1):
        bucket = classify_achievements(fetch_achievement_info(appid))
        if bucket == "with":
            mark_with(appid)
            with_n += 1
        elif bucket == "store_zero":
            mark_store_zero(appid)
            zero_n += 1
        elif bucket == "store_empty":
            mark_store_empty(appid)
            empty_n += 1
        else:
            unknown_n += 1
        log.info("[%d/%d] %d → %s", i, total, appid, bucket)
        if i < total:
            time.sleep(_REQUEST_DELAY)

    log.info(SEPARATOR)
    log.info(
        "Готово: with=%d, store_zero=%d, store_empty=%d, unknown=%d (перезапрос)",
        with_n,
        zero_n,
        empty_n,
        unknown_n,
    )
    log.info(SEPARATOR)


if __name__ == "__main__":
    main()
