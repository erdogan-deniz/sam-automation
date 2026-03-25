"""Обновление steamLoginSecure через долгоживущий steamRememberLogin токен."""

from __future__ import annotations

import http.cookiejar
import logging

from .storage import _REMEMBER_LOGIN_FILE, _save_manual_cookie

log = logging.getLogger("sam_automation")


def _make_cookie(domain: str, name: str, value: str) -> http.cookiejar.Cookie:
    """Создаёт объект http.cookiejar.Cookie для ручной установки."""
    import http.cookiejar as cj

    return cj.Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )


def _web_refresh() -> dict | None:
    """Обновляет steamLoginSecure через steamRememberLogin без перелогина.

    steamRememberLogin — долгоживущий токен (месяцы), выданный Steam при входе.
    Steam обменивает его на новый steamLoginSecure при обращении к login/home.
    """
    if not _REMEMBER_LOGIN_FILE.exists():
        return None
    remember = _REMEMBER_LOGIN_FILE.read_text(encoding="utf-8").strip()
    if not remember:
        return None

    import http.cookiejar
    import urllib.request

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar)
    )
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]

    jar.set_cookie(
        _make_cookie("steamcommunity.com", "steamRememberLogin", remember)
    )

    try:
        opener.open("https://steamcommunity.com/login/home/?goto=", timeout=10)
        for c in jar:
            if c.name == "steamLoginSecure" and c.value and "||" in c.value:
                val = c.value
                _save_manual_cookie(val)
                log.info("Сессия обновлена через steamRememberLogin")
                return {"steamLoginSecure": val}
    except Exception as e:
        log.debug("web_refresh: %s", e)

    return None
