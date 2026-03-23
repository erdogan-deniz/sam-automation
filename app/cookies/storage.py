"""Локальное хранилище JWT-кук: manual_cookie.txt и remember_login.txt."""

from __future__ import annotations

import base64
import json
import logging
import time

from app.auth._constants import _CRED_DIR

log = logging.getLogger("sam_automation")

_MANUAL_COOKIE_FILE = _CRED_DIR / "manual_cookie.txt"
_REMEMBER_LOGIN_FILE = _CRED_DIR / "remember_login.txt"


def _jwt_expired(cookie_val: str) -> bool:
    """Проверяет срок действия JWT access token без обращения к серверу.

    steamLoginSecure = "{steamid64}||{jwt}". JWT payload содержит поле exp (unix ts).
    """
    try:
        token = (
            cookie_val.split("||", 1)[1] if "||" in cookie_val else cookie_val
        )
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # восстанавливаем padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp", 0)
        return (
            time.time() > exp - 60
        )  # считаем просроченным за 60с до истечения
    except Exception:
        return False  # не можем определить — считаем валидным


def _load_manual_cookie() -> dict | None:
    """Читает ручной steamLoginSecure cookie из файла."""
    if not _MANUAL_COOKIE_FILE.exists():
        return None
    try:
        val = _MANUAL_COOKIE_FILE.read_text(encoding="utf-8").strip()
        if "||" not in val or len(val.split("||", 1)[1]) < 100:
            return None  # не похоже на JWT формат
        if _jwt_expired(val):
            log.info("Сохранённый cookie истёк — нужен новый")
            return None
        log.info("Использую сохранённый steamLoginSecure cookie")
        return {"steamLoginSecure": val}
    except Exception:
        return None


def _save_manual_cookie(val: str) -> None:
    """Сохраняет steamLoginSecure cookie в файл для будущих запусков.

    Playwright возвращает значение в URL-encoded форме (%7C%7C вместо ||).
    Декодируем перед сохранением.
    """
    from urllib.parse import unquote

    val = unquote(val.strip())
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _MANUAL_COOKIE_FILE.write_text(val.strip(), encoding="utf-8")
    log.info("Cookie сохранён в %s", _MANUAL_COOKIE_FILE)


def _save_remember_login(val: str) -> None:
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _REMEMBER_LOGIN_FILE.write_text(val.strip(), encoding="utf-8")
    log.debug("steamRememberLogin сохранён")
