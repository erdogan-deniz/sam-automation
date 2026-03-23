"""Получение JWT-кук Steam Community.

Субмодули:
  storage     — manual_cookie.txt, remember_login.txt, jwt_expired()
  web_refresh — обновление через steamRememberLogin
  dpapi       — Win32 DPAPI расшифровка и _copy_shared
  firefox     — SQLite extractor (Firefox)
  chrome      — DPAPI+AES-GCM extractor (Chrome/Edge/Brave)
  cdp         — Chrome DevTools Protocol extractor
  playwright  — Playwright headless + visible login

Публичный API: get_web_cookies(username, *, interactive=True)
"""

from __future__ import annotations

import logging

from app.auth.jwt import _jwt_from_refresh_token

from .cdp import _cdp_steam_cookies
from .chrome import _chrome_steam_cookies
from .firefox import _firefox_steam_cookies
from .playwright import _playwright_login, _playwright_steam_cookies
from .storage import _load_manual_cookie, _save_manual_cookie
from .web_refresh import _web_refresh

log = logging.getLogger("sam_automation")


def _browser_cookies_silent() -> dict | None:
    """Тихое извлечение куки: CDP → Firefox (SQLite) → Chrome/Edge (DPAPI) → Playwright headless.

    Не требует ввода данных. CDP работает даже когда браузер запущен.
    SQLite может не сработать если браузер держит файл заблокированным.
    """
    cookies = _cdp_steam_cookies()
    if cookies:
        return cookies

    cookies = _firefox_steam_cookies()
    if cookies:
        return cookies

    cookies = _chrome_steam_cookies()
    if cookies:
        return cookies

    return _playwright_steam_cookies(visible_fallback=False)


def _browser_cookies() -> dict | None:
    """Читает Steam Community куки из браузеров (включая открытие окна браузера)."""
    return _playwright_steam_cookies(visible_fallback=True)


def get_web_cookies(username: str, *, interactive: bool = True) -> dict | None:
    """Возвращает JWT-куки веб-сессии Steam Community.

    Порядок попыток (все автоматические, без ввода данных):
      1. Сохранённый access token (~24ч)
      2. steamRememberLogin — web-обновление без перелогина (месяцы)
      3. JWT refresh token через CM — обновление без 2FA (месяцы)
      4. Браузер (один раз, потом пп. 1-3 работают автоматически)
    """
    # 1. Действующий сохранённый token
    cookies = _load_manual_cookie()
    if cookies:
        return cookies

    # 2. Обновление через steamRememberLogin (web, без CM)
    cookies = _web_refresh()
    if cookies:
        return cookies

    # 3. Обновление через JWT refresh token (CM протокол)
    cookies = _jwt_from_refresh_token()
    if cookies:
        _save_manual_cookie(cookies["steamLoginSecure"])
        return cookies

    if not interactive:
        log.info(
            "Нет сохранённого cookie. Запусти скрипт интерактивно для входа."
        )
        return None

    # 4. Первичный вход через браузер (один раз)
    cookies = _playwright_login()
    if cookies:
        return cookies

    return None
