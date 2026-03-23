"""Чтение данных Steam из реестра Windows и конвертация Steam ID."""

from __future__ import annotations

import logging
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

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"
        ) as key:
            username, _ = winreg.QueryValueEx(key, "AutoLoginUser")
            return username or None
    except Exception:
        return None


def steamid64_to_id3(steam_id64: str) -> int:
    """Конвертирует Steam ID64 в ID3 (используется в папке userdata)."""
    return int(steam_id64) - STEAM_ID64_BASE
