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


def read_installed_app_ids(steam_path: str) -> list[int]:
    """Читает App ID всех установленных приложений через appmanifest_*.acf файлы.

    Сканирует все папки библиотек Steam (основную + дополнительные с других дисков).
    Путь к библиотекам берётся из steamapps/libraryfolders.vdf.
    """
    # Собираем пути всех steamapps папок
    steamapps_dirs: list[Path] = [Path(steam_path) / "steamapps"]

    lf_path = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
    if lf_path.exists():
        content = lf_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'"path"\s+"([^"]+)"', content):
            extra = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
            if extra.exists() and extra not in steamapps_dirs:
                steamapps_dirs.append(extra)

    app_ids: list[int] = []
    for folder in steamapps_dirs:
        manifests = list(folder.glob("appmanifest_*.acf"))
        for manifest in manifests:
            try:
                app_ids.append(int(manifest.stem.split("_", 1)[1]))
            except (ValueError, IndexError):
                pass
        log.debug("steamapps %s: %d манифестов", folder, len(manifests))

    log.info("Найдено %d установленных приложений в %d папках библиотек",
             len(app_ids), len(steamapps_dirs))
    return app_ids


def read_shared_app_ids(steam_path: str, steam_id: str) -> list[int]:
    """Читает App ID из sharedconfig.vdf — Steam Cloud библиотека (кросс-машинная).

    Содержит приложения, с которыми пользователь взаимодействовал на ЛЮБОМ компьютере.
    Путь: userdata/<id3>/7/remote/sharedconfig.vdf
    """
    id3 = steamid64_to_id3(steam_id)
    vdf_path = Path(steam_path) / "userdata" / str(id3) / "7" / "remote" / "sharedconfig.vdf"

    if not vdf_path.exists():
        log.warning("sharedconfig.vdf не найден: %s", vdf_path)
        return []

    log.info("Читаю sharedconfig из %s", vdf_path)
    content = vdf_path.read_text(encoding="utf-8", errors="replace")
    app_ids = _extract_app_ids_from_vdf(content)
    log.info("Найдено %d приложений в sharedconfig.vdf", len(app_ids))
    return app_ids


def read_userdata_app_ids(steam_path: str, steam_id: str) -> list[int]:
    """Читает App ID из подпапок userdata/<id3>/.

    Steam создаёт папку для каждого приложения, с которым пользователь
    когда-либо взаимодействовал (сохранения, достижения, скриншоты).
    Нечисловые папки (config, ugc, ...) пропускаются.
    """
    id3 = steamid64_to_id3(steam_id)
    userdata_path = Path(steam_path) / "userdata" / str(id3)

    if not userdata_path.exists():
        log.warning("userdata папка не найдена: %s", userdata_path)
        return []

    app_ids: list[int] = []
    for entry in userdata_path.iterdir():
        if entry.is_dir():
            try:
                app_ids.append(int(entry.name))
            except ValueError:
                pass

    log.info("Найдено %d приложений в userdata", len(app_ids))
    return app_ids


def read_registry_app_ids() -> list[int]:
    """Читает App ID всех приложений из Windows Registry.

    HKCU\\Software\\Valve\\Steam\\Apps — полный список владения:
    купленные, F2P, family sharing, никогда не запускавшиеся.
    """
    try:
        import winreg
        app_ids: list[int] = []
        key_path = r"Software\Valve\Steam\Apps"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    try:
                        app_ids.append(int(subkey_name))
                    except ValueError:
                        pass
                    i += 1
                except OSError:
                    break
        log.info("Найдено %d приложений в Windows Registry", len(app_ids))
        return app_ids
    except Exception as e:
        log.warning("Windows Registry: %s", e)
        return []


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
