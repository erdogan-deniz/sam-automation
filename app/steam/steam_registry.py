"""Чтение данных Steam из реестра Windows и конвертация Steam ID."""

from __future__ import annotations

import logging
from pathlib import Path

from ..exceptions import SAMError

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
                    # Пустой InstallPath НЕ валиден: Path("").exists() == True
                    # (пустая строка резолвится в текущую директорию) → без
                    # гварда `if path` вернулся бы "" как «путь к Steam».
                    if path and Path(path).exists():
                        log.debug("Steam найден в реестре: %s", path)
                        return path
            except OSError:
                # FileNotFoundError (нет ключа) — штатно; но PermissionError и
                # прочие OSError из OpenKey/QueryValueEx НЕ должны рушить весь
                # поиск — просто пробуем следующий хайв/стандартные пути.
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


def steamid64_to_id3(steam_id64: str) -> int:
    """Конвертирует Steam ID64 в ID3 (используется в папке userdata).

    Raises:
        SAMError: если steam_id64 пустой, нечисловой или меньше базы ID64
            (иначе получили бы сырой ValueError или отрицательный id3-путь,
            уводящий read_library_app_ids в несуществующую папку userdata).
    """
    raw = (steam_id64 or "").strip()
    if not raw.isdigit():
        raise SAMError(
            f"Некорректный Steam ID64: {steam_id64!r} — ожидались только цифры"
        )
    value = int(raw)
    if value < STEAM_ID64_BASE:
        raise SAMError(
            f"Steam ID64 {value} меньше базы {STEAM_ID64_BASE} — "
            f"не похоже на валидный 64-битный Steam ID"
        )
    return value - STEAM_ID64_BASE
