"""Сканирование библиотеки Steam → запись all.txt.

Собирает ID из трёх источников:
  1. localconfig.vdf — локальная история этой машины (основной источник)
  2. Steam API       — купленные игры (без никогда не запускавшихся F2P)
  3. Steam CM        — все лицензии аккаунта (требует логин, самый полный)

Использование:
    python scripts/scan.py  # читает config.yaml, пишет all.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging
import os

# Должно быть до любого импорта protobuf (используется steam библиотекой)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.cache import ALL_IDS_FILE, save_game_names
from app.config import load_config
from app.id_file import _atomic_write_text, read_ids_ordered
from app.logging_setup import SEPARATOR, setup_logging
from app.steam import find_steam_path, read_library_app_ids, resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")

# Если после слияния всех источников библиотека схлопнулась ниже этой доли от
# прежнего all.txt — это почти наверняка транзиентный отказ источника (упавший
# CM/API), а не реальная потеря игр. all.txt в таком случае НЕ перезаписываем,
# чтобы не затереть накопленный мастер-список (обход — флаг --allow-shrink).
_SHRINK_FLOOR = 0.5


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


def _read_api_ids(api_key: str, steam_id: str) -> list[int]:
    """Читает App ID из Steam API (IPlayerService/GetOwnedGames), сохраняет имена игр.

    validate() уже гарантирует непустой api_key до вызова источников, поэтому
    отдельной ветки «ключ не задан» здесь нет.
    """
    log.info("Получение ID приложений библиотеки Steam через Steam API")

    try:
        from app.steam import fetch_owned_games

        games = fetch_owned_games(api_key, steam_id)
    except Exception as e:
        log.warning("Steam API: %s", e)
        return []

    # Сохранение имён — в отдельном try: сбой записи names.json НЕ должен
    # ронять весь список App ID (иначе транзиентная ошибка записи имён
    # обнуляла бы источник API целиком).
    names = {
        g["appid"]: g["name"]
        for g in games
        if g.get("appid") is not None and g.get("name")
    }
    if names:
        try:
            save_game_names(names)
            log.info("Сохранено имён игр: %d", len(names))
        except Exception as e:
            log.warning("Не удалось сохранить имена игр: %s", e)

    # g.get("appid") + пропуск None — защита от битой записи в ответе API.
    return [g["appid"] for g in games if g.get("appid") is not None]


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


def main(allow_shrink: bool = False) -> None:
    """Сканирует библиотеку Steam из трёх источников и записывает all.txt.

    allow_shrink: обходит floor-guard (см. _SHRINK_FLOOR) — осознанное согласие
    перезаписать all.txt даже при резкой усадке библиотеки.
    """
    print()

    setup_logging(
        verbose=False, name="scan_achievements", category="achievements/scan"
    )
    log.info("Сканирование приложений библиотеки Steam")
    log.info(SEPARATOR)
    cfg = load_config()

    # Резолвим Steam ID (vanity-имя/URL → ID64) ДО валидации: validate шлёт
    # steam_id в GetPlayerSummaries, которому нужен числовой ID64. Числовой ID64
    # резолвер пропускает без сети. Пустой steam_id НЕ резолвим — пусть validate
    # выдаст локальную ошибку «steam_id is missing» без лишнего сетевого вызова.
    # (Порядок resolve→validate отличается от boost/cards, где validate раньше.)
    if cfg.steam_id:
        try:
            cfg.steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
        except (RuntimeError, KeyError) as e:
            # KeyError — аномальный ответ ResolveVanityURL (success=1 без
            # steamid); RuntimeError — сеть/неуспех. Оба → чистый exit, не трейс.
            log.error("Не удалось определить Steam ID: %s", e)
            sys.exit(1)

    validate(cfg)

    log.info("Ваш Steam ID: %s", cfg.steam_id)
    steam_path = cfg.steam_path or find_steam_path()

    prev_ids = (
        set(read_ids_ordered(ALL_IDS_FILE)) if ALL_IDS_FILE.exists() else set()
    )

    combined: list[int] = []
    seen: set[int] = set()

    def _merge(new_ids: list[int]) -> None:
        """Добавляет новые ID в combined, исключая дубликаты.

        Порядок источников важен только для дедупа: какой источник «застолбил»
        дубль. На диск (см. ниже) идёт числовая сортировка, а не этот порядок.
        """
        for gid in new_ids:
            if gid not in seen:
                seen.add(gid)
                combined.append(gid)

    def _new_in_combined() -> int:
        """Сколько ID в combined отсутствовало в прежнем all.txt (маргинально)."""
        return sum(1 for gid in combined if gid not in prev_ids)

    # Счётчики согласованно-маргинальные: дельта каждого шага = прирост new
    # относительно предыдущего шага, поэтому три строки суммируются в new_count.
    log.info(SEPARATOR)
    _merge(_read_vdf_ids(steam_path, cfg.steam_id))
    new_after_vdf = _new_in_combined()
    log.info(
        "Найдено %d новых ID приложений библиотеки Steam из локального файла",
        new_after_vdf,
    )

    log.info(SEPARATOR)
    _merge(_read_api_ids(cfg.steam_api_key, cfg.steam_id))
    new_after_api = _new_in_combined()
    log.info(
        "Найдено %d новых ID приложений библиотеки Steam через Steam API",
        new_after_api - new_after_vdf,
    )

    log.info(SEPARATOR)
    _merge(_read_cm_ids(steam_path))
    new_after_cm = _new_in_combined()
    log.info(
        "Найдено %d новых ID приложений библиотеки Steam через Steam Client Master",
        new_after_cm - new_after_api,
    )

    new_count = new_after_cm

    if not combined:
        log.error("Ни один источник не вернул ID. Проверь steam_id и конфиг.")
        sys.exit(1)

    if (
        prev_ids
        and not allow_shrink
        and len(combined) < _SHRINK_FLOOR * len(prev_ids)
    ):
        log.error(
            "Библиотека схлопнулась с %d до %d — вероятен транзиентный отказ "
            "источника; all.txt НЕ перезаписан. Повтори прогон или запусти с "
            "--allow-shrink",
            len(prev_ids),
            len(combined),
        )
        sys.exit(1)

    log.info(SEPARATOR)
    log.info("Итого: найдено %d ID приложений библиотеки Steam", len(combined))
    log.info(
        "Итого: найдено %d новых ID приложений библиотеки Steam", new_count
    )

    # На диск — числовая сортировка (стабильный diff), а не порядок дедупа.
    # _atomic_write_text сам делает mkdir(parents=True) для каталога.
    _atomic_write_text(
        ALL_IDS_FILE, "\n".join(str(i) for i in sorted(combined)) + "\n"
    )
    log.info(
        "Полученые ID приложений библиотеки Steam записаны в локальный файл: %s",
        ALL_IDS_FILE,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает CLI-аргументы scan (вынесено из __main__ для тестируемости)."""
    parser = argparse.ArgumentParser(
        description="Сканирование библиотеки Steam → all.txt"
    )
    parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help="перезаписать all.txt даже при резкой усадке библиотеки "
        "(обход защиты от транзиентного отказа источника)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    main(allow_shrink=_parse_args().allow_shrink)
