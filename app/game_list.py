"""Загрузка списка ID игр из конфигурации, файла или Steam API (с кэшем)."""

from __future__ import annotations

import logging
from pathlib import Path

from .cache import ALL_IDS_FILE
from .config import Config

log = logging.getLogger("sam_automation")


def load_game_ids(cfg: Config) -> list[int]:
    """Собирает итоговый список ID игр из доступных источников.

    Приоритет: config.game_ids → ids.txt → cfg.game_ids_file.
    Для сбора ID из Steam-источников используй scan.py.
    """
    ids: list[int] = list(cfg.game_ids)

    # Если ids.txt существует и нет явных переопределений — читаем из него
    if not ids and not cfg.game_ids_file and ALL_IDS_FILE.exists():
        log.info("Читаю список игр из %s", ALL_IDS_FILE)
        for line in ALL_IDS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    ids.append(int(line))
                except ValueError:
                    log.warning("Невалидная строка в %s: %r", ALL_IDS_FILE, line)
        if ids:
            log.info("Загружено %d игр из %s", len(ids), ALL_IDS_FILE)

    if not ids:
        log.error(
            "Список игр не найден. Запусти scan.py для формирования ids.txt"
        )

    # Загружаем из файла, если указан
    if cfg.game_ids_file:
        file_path = Path(cfg.game_ids_file)
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        ids.append(int(line))
                    except ValueError:
                        log.warning("Пропущена невалидная строка в %s: %s", file_path, line)
        else:
            log.warning("Файл game_ids не найден: %s", file_path)

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique: list[int] = []
    for gid in ids:
        if gid not in seen:
            seen.add(gid)
            unique.append(gid)

    # Исключаем exclude_ids
    exclude = set(cfg.exclude_ids)
    result = [gid for gid in unique if gid not in exclude]

    if exclude:
        excluded_count = len(unique) - len(result)
        if excluded_count:
            log.info("Исключено %d игр из списка", excluded_count)

    return result
