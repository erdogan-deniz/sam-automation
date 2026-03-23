"""Извлечение Steam Community кук из Chrome/Edge/Brave (DPAPI + AES-GCM)."""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import tempfile
from pathlib import Path

from .dpapi import _copy_shared, _dpapi_decrypt

log = logging.getLogger("sam_automation")

# Chromium-based браузеры: ключ = подстрока ProgId, значение = (channel, profile_rel_path)
# channel=None → браузер не является системным каналом Playwright; exe читается из реестра
_BROWSER_DEFS: dict[str, tuple[str | None, str]] = {
    "chrome": ("chrome", "AppData/Local/Google/Chrome/User Data"),
    "msedge": ("msedge", "AppData/Local/Microsoft/Edge/User Data"),
    "edge": ("msedge", "AppData/Local/Microsoft/Edge/User Data"),
    "yandex": (None, "AppData/Local/Yandex/YandexBrowser/User Data"),
    "brave": (None, "AppData/Local/BraveSoftware/Brave-Browser/User Data"),
    "opera": (None, "AppData/Roaming/Opera Software/Opera Stable"),
    "vivaldi": (None, "AppData/Local/Vivaldi/User Data"),
}


def _default_browser() -> tuple[str | None, str | None, str | None]:
    """Возвращает (channel, exe_path, profile_path) для браузера по умолчанию.

    Читает ProgId из HKCU\\...\\UrlAssociations\\http\\UserChoice.
    Путь к exe берётся из реестра (SOFTWARE\\Classes\\{ProgId}\\shell\\open\\command),
    а не хардкодится — работает для любой версии и пути установки.
    """
    import re
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]

        prog_id_lower = prog_id.lower()

        channel, profile = None, None
        for keyword, (ch, profile_rel) in _BROWSER_DEFS.items():
            if keyword in prog_id_lower:
                channel = ch
                profile = str(Path.home() / profile_rel)
                break

        exe = None
        if channel is None:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    sub = rf"SOFTWARE\Classes\{prog_id}\shell\open\command"
                    with winreg.OpenKey(root, sub) as k:
                        cmd = winreg.QueryValueEx(k, "")[0]
                        m = re.match(r'"([^"]+\.exe)"', cmd)
                        if m:
                            exe = m.group(1)
                            break
                except Exception:
                    pass

        return channel, exe, profile

    except Exception:
        pass
    return None, None, None


def _decrypt_chrome_value(encrypted_value: bytes, key: bytes) -> str | None:
    """Расшифровывает значение куки Chrome.

    v10 = AES-256-GCM (Chrome < 127) — требует пакет cryptography.
    v20 = App-Bound Encryption (Chrome 127+) — невозможно без Chrome.
    Без префикса = старый DPAPI напрямую.
    """
    if not encrypted_value:
        return None

    prefix = encrypted_value[:3]

    if prefix == b"v10":
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            log.debug(
                "cryptography не установлен — Chrome v10 cookies пропущены"
            )
            return None
        try:
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:]
            return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
        except Exception:
            return None

    if prefix == b"v20":
        # App-Bound Encryption (Chrome 127+) — пропускаем
        return None

    # Старый формат: DPAPI без AES обёртки
    try:
        result = _dpapi_decrypt(encrypted_value)
        return result.decode("utf-8") if result else None
    except Exception:
        return None


def _chrome_steam_cookies() -> dict | None:
    """Читает Steam Community куки из Chrome/Edge/Brave через DPAPI + AES-GCM.

    Работает для v10 куки (Chrome < 127). Chrome 127+ использует App-Bound
    Encryption (v20) — такие куки пропускаются.
    """
    # Используем браузер по умолчанию первым, затем остальные
    default_channel, _default_exe, default_profile = _default_browser()
    default_profile_path = Path(default_profile) if default_profile else None

    all_profile_dirs = [
        # Steam-клиент (CEF Chromium) — всегда доступен если Steam запущен
        Path.home() / "AppData" / "Local" / "Steam" / "htmlcache",
        Path.home()
        / "AppData"
        / "Local"
        / "Yandex"
        / "YandexBrowser"
        / "User Data",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
        Path.home()
        / "AppData"
        / "Local"
        / "BraveSoftware"
        / "Brave-Browser"
        / "User Data",
        Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data",
        Path.home() / "AppData" / "Local" / "Vivaldi" / "User Data",
    ]
    if default_profile_path and default_profile_path not in all_profile_dirs:
        all_profile_dirs.insert(0, default_profile_path)
    elif default_profile_path and default_profile_path in all_profile_dirs:
        all_profile_dirs.remove(default_profile_path)
        all_profile_dirs.insert(0, default_profile_path)

    for user_data in all_profile_dirs:
        local_state = user_data / "Local State"
        if not local_state.exists():
            continue

        try:
            state = json.loads(local_state.read_text(encoding="utf-8"))
            enc_key_b64 = state.get("os_crypt", {}).get("encrypted_key", "")
            if not enc_key_b64:
                continue
            enc_key = base64.b64decode(enc_key_b64)
            if enc_key[:5] == b"DPAPI":
                enc_key = enc_key[5:]
            key = _dpapi_decrypt(enc_key)
            if not key:
                continue
        except Exception as e:
            log.debug("Chrome key (%s): %s", user_data.name, e)
            continue

        for profile in (".", "Default", "Profile 1", "Profile 2"):
            for rel in (
                Path(profile) / "Network" / "Cookies",
                Path(profile) / "Cookies",
            ):
                cookies_path = user_data / rel
                if not cookies_path.exists():
                    continue

                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_db = Path(tmpdir) / "Cookies"
                    try:
                        _copy_shared(cookies_path, tmp_db)
                        for ext in ("-wal", "-shm"):
                            src = Path(str(cookies_path) + ext)
                            if src.exists():
                                _copy_shared(
                                    src, Path(tmpdir) / ("Cookies" + ext)
                                )
                        conn = sqlite3.connect(tmp_db)
                        try:
                            cur = conn.execute(
                                "SELECT name, encrypted_value FROM cookies "
                                "WHERE (host_key LIKE '%steamcommunity.com' OR host_key LIKE '%steam.tv')"
                                " AND expires_utc > 0"
                            )
                            cookies = {}
                            for name, enc_val in cur:
                                val = _decrypt_chrome_value(bytes(enc_val), key)
                                if val:
                                    cookies[name] = val
                        finally:
                            conn.close()
                    except Exception as e:
                        log.debug(
                            "Chrome cookies (%s/%s): %s",
                            user_data.name,
                            profile,
                            e,
                        )
                        cookies = {}

                if cookies.get("steamLoginSecure"):
                    log.info(
                        "Chrome cookies: %s/%s (%s)",
                        user_data.name,
                        profile,
                        list(cookies.keys()),
                    )
                    return cookies

    return None
