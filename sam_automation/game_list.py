"""Загрузка списка ID игр из конфигурации, файла или Steam API (с кэшем)."""

from __future__ import annotations

import logging
from pathlib import Path

from .cache import ALL_IDS_FILE, load_scan_cache, save_scan_cache
from .config import Config

log = logging.getLogger("sam_automation")


def load_game_ids(cfg: Config) -> list[int]:
    """Собирает итоговый список ID игр из всех доступных источников.

    Приоритет: config.game_ids → all_ids.txt → кэш →
    [localconfig.vdf + sharedconfig.vdf + Steam API] → файл.
    """
    ids: list[int] = list(cfg.game_ids)

    # Если all_ids.txt существует и нет явных переопределений — читаем из него
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

    if not ids and not cfg.game_ids_file and cfg.steam_id:
        cached = load_scan_cache(scan_all=True)
        if cached is not None:
            ids.extend(cached)
        else:
            from .steam_local import (
                find_steam_path, read_installed_app_ids, read_library_app_ids,
                read_registry_app_ids, read_shared_app_ids, read_steam_username,
                read_userdata_app_ids,
            )
            steam_path = cfg.steam_path or find_steam_path()

            combined: list[int] = []
            seen: set[int] = set()

            def _merge(new_ids: list[int], source: str) -> int:
                added = 0
                for gid in new_ids:
                    if gid not in seen:
                        seen.add(gid)
                        combined.append(gid)
                        added += 1
                log.info("%s: %d ID (новых: %d)", source, len(new_ids), added)
                return added

            # 1. localconfig.vdf — локальная история этой машины
            if steam_path:
                try:
                    _merge(read_library_app_ids(steam_path, cfg.steam_id), "localconfig.vdf")
                except Exception as e:
                    log.warning("localconfig.vdf: %s", e)

            # 2. sharedconfig.vdf — Steam Cloud, кросс-машинная история
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
            _merge(read_registry_app_ids(), "Windows Registry")


            # 6. Steam API — все купленные игры (включая никогда не запускавшиеся)
            if cfg.steam_api_key:
                try:
                    from .steam_api import fetch_all_game_ids
                    _merge(fetch_all_game_ids(cfg.steam_api_key, cfg.steam_id), "Steam API")
                except Exception as e:
                    log.warning("Steam API: %s", e)

            # 7. Steam CM — только если токен уже кэширован (без интерактивного ввода)
            if steam_path:
                username = read_steam_username()
                if username:
                    try:
                        from .steam_cm import read_steam_cm_app_ids
                        _merge(
                            read_steam_cm_app_ids(steam_path, username, interactive=False),
                            "Steam CM",
                        )
                    except Exception as e:
                        log.warning("Steam CM: %s", e)

            if combined:
                log.info("Итого из всех источников: %d уникальных ID", len(combined))
                save_scan_cache(combined, scan_all=True)
                ids.extend(combined)
            else:
                log.warning("Ни один источник не вернул ID приложений")

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
