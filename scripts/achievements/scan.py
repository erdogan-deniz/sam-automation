"""Сканирование библиотеки Steam → запись ids.txt.

Собирает ID из трёх источников:
  1. localconfig.vdf — локальная история этой машины (основной источник)
  2. Steam API       — купленные игры (без никогда не запускавшихся F2P)
  3. Steam CM        — все лицензии аккаунта (требует логин, самый полный)

Использование:
    python scripts/achievements/scan.py  # читает config.yaml, пишет ids.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import logging
import os

# Должно быть до любого импорта protobuf (используется steam библиотекой)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.cache import ALL_IDS_FILE, save_game_names
from app.config import load_config
from app.id_file import read_ids_ordered
from app.validator import validate
from app.logging_setup import setup_logging
from app.steam import find_steam_path, read_library_app_ids

log = logging.getLogger("sam_automation")


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
    """Читает App ID из Steam API (IPlayerService/GetOwnedGames), сохраняет имена игр."""
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


def main() -> None:
    """Сканирует библиотеку Steam из трёх источников и записывает ids.txt."""
    print()

    log = setup_logging(
        verbose=False, name="scan_achievements", category="achievements/scan"
    )
    log.info("Сканирование приложений библиотеки Steam")
    log.info("═" * 80)
    cfg = load_config()
    validate(cfg)

    log.info("Ваш Steam ID: %s", cfg.steam_id)
    steam_path = cfg.steam_path or find_steam_path()

    prev_ids = (
        set(read_ids_ordered(ALL_IDS_FILE)) if ALL_IDS_FILE.exists() else set()
    )

    combined: list[int] = []
    seen: set[int] = set()

    def _merge(new_ids: list[int]) -> None:
        """Добавляет новые ID в combined, исключая дубликаты."""
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
        sys.exit(1)

    log.info("═" * 80)
    log.info("Итого: найдено %d ID приложений библиотеки Steam", len(combined))
    log.info(
        "Итого: найдено %d новых ID приложений библиотеки Steam",
        new_count
    )

    ALL_IDS_FILE.parent.mkdir(exist_ok=True)
    ALL_IDS_FILE.write_text(
        "\n".join(str(i) for i in sorted(combined)) + "\n", encoding="utf-8"
    )
    log.info("Полученые ID приложений библиотеки Steam записаны в локальный файл: %s", ALL_IDS_FILE)


if __name__ == "__main__":
    main()
