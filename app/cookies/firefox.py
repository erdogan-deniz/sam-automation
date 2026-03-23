"""Извлечение Steam Community кук из Firefox (SQLite, без шифрования)."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path

log = logging.getLogger("sam_automation")


def _firefox_steam_cookies() -> dict | None:
    """Читает Steam Community куки напрямую из SQLite Firefox.

    Firefox не шифрует куки на уровне ОС — они хранятся открытым текстом.
    """
    profiles_dir = (
        Path.home() / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles"
    )
    if not profiles_dir.exists():
        return None

    for profile in profiles_dir.iterdir():
        cookies_db = profile / "cookies.sqlite"
        if not cookies_db.exists():
            continue

        # Firefox блокирует файл во время работы — копируем во временную папку
        # (вместе с WAL-файлом, иначе пропустим незакоммиченные транзакции)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = Path(tmpdir) / "cookies.sqlite"
            try:
                shutil.copy2(cookies_db, tmp_db)
                for ext in ("-wal", "-shm"):
                    src = Path(str(cookies_db) + ext)
                    if src.exists():
                        shutil.copy2(
                            src, Path(tmpdir) / ("cookies.sqlite" + ext)
                        )
                conn = sqlite3.connect(tmp_db)
                try:
                    cur = conn.execute(
                        "SELECT name, value FROM moz_cookies "
                        "WHERE host LIKE '%steamcommunity.com' AND expiry > strftime('%s','now')"
                    )
                    cookies = {row[0]: row[1] for row in cur}
                finally:
                    conn.close()
            except Exception as e:
                log.debug("Firefox cookies (%s): %s", profile.name, e)
                cookies = {}

        if cookies.get("steamLoginSecure"):
            log.info(
                "Firefox cookies: профиль %s (%s)",
                profile.name,
                list(cookies.keys()),
            )
            return cookies

    return None
