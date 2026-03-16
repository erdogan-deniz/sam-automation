"""Сканирование библиотеки Steam → запись all_ids.txt.

Собирает ID из шести источников:
  1. localconfig.vdf  — локальная история этой машины
  2. sharedconfig.vdf — Steam Cloud (все машины аккаунта)
  3. appmanifest      — установленные приложения (все диски)
  4. userdata         — папки с пользовательскими данными игр
  5. Windows Registry — полный список владения
  6. Steam API        — купленные игры (без никогда не запускавшихся F2P)
  7. Steam CM         — все лицензии аккаунта (требует логин, самый полный)

Использование:
    python scripts/scan.py  # читает config.yaml, пишет all_ids.txt
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import os

# Должно быть до любого импорта protobuf (используется steam библиотекой)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.config import load_config
from app.logging_setup import setup_logging
from app.steam_local import (
    find_steam_path, read_installed_app_ids, read_library_app_ids,
    read_registry_app_ids, read_shared_app_ids, read_steam_username,
    read_userdata_app_ids,
)
from app.cache import ALL_IDS_FILE


def main() -> None:
    log = setup_logging(verbose=False, name="scan")
    cfg = load_config()

    if not cfg.steam_id:
        log.error("Заполни steam_id в config.yaml")
        sys.exit(1)

    steam_path = cfg.steam_path or find_steam_path()

    combined: list[int] = []
    seen: set[int] = set()

    def _merge(new_ids: list[int], source: str) -> None:
        added = sum(1 for gid in new_ids if gid not in seen)
        for gid in new_ids:
            if gid not in seen:
                seen.add(gid)
                combined.append(gid)
        log.info("%s: %d ID (новых: %d)", source, len(new_ids), added)

    # 1. localconfig.vdf
    if steam_path:
        try:
            _merge(read_library_app_ids(steam_path, cfg.steam_id), "localconfig.vdf")
        except Exception as e:
            log.warning("localconfig.vdf: %s", e)
    else:
        log.warning("Папка Steam не найдена. Укажи steam_path в config.yaml")

    # 2. sharedconfig.vdf
    if steam_path:
        try:
            _merge(read_shared_app_ids(steam_path, cfg.steam_id), "sharedconfig.vdf")
        except Exception as e:
            log.warning("sharedconfig.vdf: %s", e)

    # 3. appmanifest_*.acf — все установленные приложения (все диски)
    if steam_path:
        try:
            _merge(read_installed_app_ids(steam_path), "appmanifest (установленные)")
        except Exception as e:
            log.warning("appmanifest: %s", e)

    # 4. userdata/<id3>/ — папки приложений с пользовательскими данными
    if steam_path:
        try:
            _merge(read_userdata_app_ids(steam_path, cfg.steam_id), "userdata")
        except Exception as e:
            log.warning("userdata: %s", e)

    # 5. Windows Registry — полный список владения (всё что видно в Steam)
    try:
        _merge(read_registry_app_ids(), "Windows Registry")
    except Exception as e:
        log.warning("Windows Registry: %s", e)

    # 6. Steam API
    if cfg.steam_api_key:
        try:
            from app.steam_api import fetch_all_game_ids
            _merge(fetch_all_game_ids(cfg.steam_api_key, cfg.steam_id), "Steam API")
        except Exception as e:
            log.warning("Steam API: %s", e)
    else:
        log.info("steam_api_key не задан — пропускаю Steam API")

    # 7. Steam CM — все лицензии аккаунта (самый полный источник, требует логин)
    if steam_path:
        try:
            username = read_steam_username()
        except Exception as e:
            log.warning("Steam CM (определение username): %s", e)
            username = None
        if username:
            try:
                from app.steam_cm import read_steam_cm_app_ids
                _merge(read_steam_cm_app_ids(steam_path, username, interactive=True), "Steam CM")
            except KeyboardInterrupt:
                log.info("Steam CM: отменено пользователем")
            except Exception as e:
                log.warning("Steam CM: %s", e)
        else:
            log.info("Steam CM: не удалось определить username")

    if not combined:
        log.error("Ни один источник не вернул ID. Проверь steam_id и конфиг.")
        sys.exit(1)

    log.info("Итого: %d уникальных ID", len(combined))
    ALL_IDS_FILE.parent.mkdir(exist_ok=True)
    ALL_IDS_FILE.write_text("\n".join(str(i) for i in combined) + "\n", encoding="utf-8")
    log.info("Записано в %s", ALL_IDS_FILE)


if __name__ == "__main__":
    main()
