"""Чтение списка приложений из локальных файлов Steam (localconfig.vdf)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .steam_registry import (  # noqa: F401
    find_steam_path,
    read_steam_username,
    steamid64_to_id3,
)

log = logging.getLogger("sam_automation")


def _extract_app_ids_from_vdf(content: str) -> list[int]:
    """Извлекает все App ID из содержимого localconfig.vdf.

    Структура localconfig.vdf:
        "UserLocalConfigStore"
        {
            "Software"
            {
                "Valve"
                {
                    "Steam"
                    {
                        "apps"
                        {
                            "10"
                            {
                                "LastPlayed"  "..."
                            }
    """
    # Ищем вложенную секцию Software > Valve > Steam > apps
    match = re.search(
        r'"Software"\s*\{\s*"Valve"\s*\{\s*"Steam"\s*\{\s*"apps"\s*\{',
        content,
        re.DOTALL,
    )
    if not match:
        log.warning("Секция 'Software/Valve/Steam/apps' не найдена в VDF файле")
        return []

    # Позиция сразу после последнего { (открывающей скобки apps)
    start = match.end()
    depth = 1
    pos = start
    while pos < len(content) and depth > 0:
        if content[pos] == "{":
            depth += 1
        elif content[pos] == "}":
            depth -= 1
        pos += 1

    apps_block = content[start : pos - 1]

    # App ID — числовые ключи верхнего уровня (глубина depth=1 внутри apps)
    # { может быть на следующей строке
    app_ids: list[int] = []
    for m in re.finditer(r'"(\d+)"\s*\n?\s*\{', apps_block):
        try:
            app_ids.append(int(m.group(1)))
        except ValueError:
            pass

    return app_ids


def read_library_app_ids(steam_path: str, steam_id: str) -> list[int]:
    """Читает все App ID из localconfig.vdf — полная библиотека включая демо и ПО.

    Args:
        steam_path: путь к папке Steam (например C:/Program Files (x86)/Steam)
        steam_id: Steam ID64 пользователя (17 цифр)

    Returns:
        Список всех App ID из библиотеки.
    """
    id3 = steamid64_to_id3(steam_id)
    vdf_path = (
        Path(steam_path) / "userdata" / str(id3) / "config" / "localconfig.vdf"
    )

    if not vdf_path.exists():
        raise FileNotFoundError(
            f"Локальный Steam файл localconfig.vdf не найден: {vdf_path}\n"
            f"Убедись, что: путь к Steam файлу указан верно и Вы вошли в Steam."
        )

    log.info(
        "Получение ID приложений библиотеки Steam из локального файла: %s",
        vdf_path,
    )

    content = vdf_path.read_text(encoding="utf-8", errors="replace")
    app_ids = _extract_app_ids_from_vdf(content)

    log.info("Найдено %d ID приложений библиотеки Steam из локального файла", len(app_ids))

    return app_ids
