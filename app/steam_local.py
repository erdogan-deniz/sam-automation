"""Чтение списка приложений из локальных файлов Steam (localconfig.vdf)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("sam_automation")

STEAM_ID64_BASE = 76561197960265728


def find_steam_path() -> str | None:
    """Ищет путь установки Steam через реестр Windows и стандартные пути."""
    try:
        import winreg
        for hive, key_path in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam"),
        ]:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    path, _ = winreg.QueryValueEx(key, "InstallPath")
                    if Path(path).exists():
                        log.debug("Steam найден в реестре: %s", path)
                        return path
            except FileNotFoundError:
                continue
    except ImportError:
        pass

    for path in [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        r"D:\Steam",
        r"D:\Program Files (x86)\Steam",
    ]:
        if Path(path).exists():
            log.debug("Steam найден по стандартному пути: %s", path)
            return path

    return None


def read_steam_username() -> str | None:
    """Читает имя последнего залогиненного пользователя из реестра Windows."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            username, _ = winreg.QueryValueEx(key, "AutoLoginUser")
            return username or None
    except Exception:
        return None


def steamid64_to_id3(steam_id64: str) -> int:
    """Конвертирует Steam ID64 в ID3 (используется в папке userdata)."""
    return int(steam_id64) - STEAM_ID64_BASE


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
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1

    apps_block = content[start:pos - 1]

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
    vdf_path = Path(steam_path) / "userdata" / str(id3) / "config" / "localconfig.vdf"

    if not vdf_path.exists():
        raise FileNotFoundError(
            f"localconfig.vdf не найден: {vdf_path}\n"
            f"Убедись что Steam Path указан верно и ты входил в Steam с этого аккаунта."
        )

    log.info("Читаю библиотеку из %s", vdf_path)
    content = vdf_path.read_text(encoding="utf-8", errors="replace")
    app_ids = _extract_app_ids_from_vdf(content)
    log.info("Найдено %d приложений в локальной библиотеке Steam", len(app_ids))
    return app_ids
