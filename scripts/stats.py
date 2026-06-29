"""Сводка по библиотеке достижений: with/without/unlocked/error + прогресс.

Читает data/games/ids/all.txt и прогресс-файлы достижений, печатает срез
состояния библиотеки.

Использование:
    python scripts/stats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache import (  # noqa: E402
    ALL_IDS_FILE,
    load_done_ids,
    load_error_ids,
    load_no_achievements_ids,
)
from app.id_file import load_ids_file  # noqa: E402
from app.logging_setup import ensure_utf8_stdout  # noqa: E402
from app.stats import format_library_stats, library_stats  # noqa: E402


def main() -> None:
    ensure_utf8_stdout()
    stats = library_stats(
        load_ids_file(ALL_IDS_FILE),
        load_done_ids(),
        load_error_ids(),
        load_no_achievements_ids(),
    )
    print(format_library_stats(stats))


if __name__ == "__main__":
    main()
