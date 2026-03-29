"""Извлечение Steam Community кук через Playwright (headless + visible login)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.auth import _JWT_REFRESH_FILE, _jwt_web_cookies, _load_session

from .chrome import _default_browser
from .storage import _jwt_expired, _save_manual_cookie, _save_remember_login

log = logging.getLogger("sam_automation")


def _playwright_steam_cookies(*, visible_fallback: bool = True) -> dict | None:
    """Извлекает Steam JWT cookies через Playwright.

    Шаг 1: пробует профиль браузера по умолчанию (тихо, без окна).
    Шаг 2 (только если visible_fallback=True): открывает видимое окно для входа.
    Playwright использует CDP → читает HttpOnly cookies напрямую,
    минуя v20-шифрование SQLite-файла Chrome/Edge.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.debug("playwright не установлен (pip install playwright)")
        return None

    def _launch_kwargs(channel: str | None, exe: str | None) -> dict:
        """Формирует kwargs для pw.chromium.launch[_persistent_context]."""
        if channel:
            return {"channel": channel}
        if exe and Path(exe).exists():
            return {"executable_path": exe}
        return {}  # встроенный Playwright Chromium

    def_channel, def_exe, def_profile = _default_browser()
    browser_name = def_channel or (
        Path(def_exe).stem if def_exe else "chromium"
    )
    log.debug("Playwright: браузер по умолчанию — %s", browser_name)

    all_browsers: list[tuple[str | None, str | None, str | None]] = [
        (def_channel, def_exe, def_profile),
        (
            "msedge",
            None,
            str(Path.home() / "AppData/Local/Microsoft/Edge/User Data"),
        ),
        (
            "chrome",
            None,
            str(Path.home() / "AppData/Local/Google/Chrome/User Data"),
        ),
    ]
    seen: set[str] = set()
    unique_browsers = []
    for ch, exe, prof in all_browsers:
        key = ch or exe or "builtin"
        if key not in seen:
            seen.add(key)
            unique_browsers.append((ch, exe, prof))

    with sync_playwright() as pw:
        # ── Шаг 1: тихое извлечение из профиля (браузер должен быть закрыт) ──
        for channel, exe, profile_path in unique_browsers:
            if not profile_path or not Path(profile_path).exists():
                continue
            kwargs = _launch_kwargs(channel, exe)
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=True,
                    timeout=5_000,
                    **kwargs,
                )
                ctx.new_page().goto("https://steamcommunity.com", timeout=8_000)
                raw = ctx.cookies("https://steamcommunity.com")
                ctx.close()
                cookies = {c["name"]: c["value"] for c in raw}
                val = cookies.get("steamLoginSecure", "")
                if val and "||" in val and not _jwt_expired(val):
                    log.info(
                        "Playwright: JWT cookie из профиля %s", channel or exe
                    )
                    return cookies
            except Exception as e:
                log.debug("Playwright profile %s: %s", channel or exe, e)

        # ── Шаг 2: окно браузера — пользователь логинится сам ──
        if not visible_fallback:
            return None
        log.info("Playwright: открываю %s для входа в Steam...", browser_name)
        print(
            "\n[Steam] Войди в аккаунт в открывшемся браузере — окно закроется само\n"
        )

        for channel, exe, _ in unique_browsers:
            kwargs = _launch_kwargs(channel, exe)
            try:
                browser = pw.chromium.launch(headless=False, **kwargs)
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(
                    "https://steamcommunity.com/login/home/", timeout=15_000
                )

                try:
                    page.wait_for_url(
                        lambda url: "/login" not in url, timeout=300_000
                    )
                except Exception:
                    pass

                raw = ctx.cookies("https://steamcommunity.com")
                cookies = {c["name"]: c["value"] for c in raw}
                val = cookies.get("steamLoginSecure", "")
                ctx.close()
                browser.close()
                if val and "||" in val:
                    _save_manual_cookie(val)
                    log.info(
                        "Playwright: JWT cookie получен (%s)",
                        channel or exe or "chromium",
                    )
                    return cookies
                log.debug(
                    "Playwright: cookies после входа: %s", list(cookies.keys())
                )
            except Exception as e:
                log.debug("Playwright launch %s: %s", channel or exe, e)

    return None


def _try_save_cm_refresh_token() -> None:
    """После браузерного входа сохраняет CM JWT refresh_token для автоматизации scan_achievements.py."""
    if _JWT_REFRESH_FILE.exists():
        return

    saved = _load_session()
    if not saved:
        return

    username, password = saved

    print(
        "\n[Steam] scan_achievements.py тоже может работать без 2FA — нужно ввести код один раз."
    )
    answer = (
        input(
            "[Steam] Настроить автоматический вход для scan_achievements.py? [y/N]: "
        )
        .strip()
        .lower()
    )
    if answer not in ("y", "yes", "д", "да"):
        return

    log.info(
        "Получаю CM JWT refresh_token для автоматизации scan_achievements.py..."
    )
    _jwt_web_cookies(username, password)


def _playwright_login() -> dict | None:
    """Открывает окно браузера для одноразового входа в Steam.

    Использует встроенный Playwright Chromium — никаких конфликтов с установленными
    браузерами. Ждёт появления steamLoginSecure JWT cookie (до 5 минут).
    Cookie сохраняется в manual_cookie.txt и живёт ~1 год.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "playwright не установлен: pip install playwright && python -m playwright install chromium"
        )
        return None

    print("\n[Steam] Открываю браузер — войди в аккаунт, окно закроется само.")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(
                "https://steamcommunity.com/login/home/",
                timeout=60_000,
                wait_until="domcontentloaded",
            )

            deadline = time.time() + 300
            while time.time() < deadline:
                try:
                    raw = ctx.cookies("https://steamcommunity.com")
                except Exception:
                    break
                val = next(
                    (
                        c["value"]
                        for c in raw
                        if c["name"] == "steamLoginSecure"
                    ),
                    "",
                )
                if val:
                    ctx.close()
                    browser.close()
                    _save_manual_cookie(val)
                    remember = next(
                        (
                            c["value"]
                            for c in raw
                            if c["name"] == "steamRememberLogin"
                        ),
                        "",
                    )
                    if remember:
                        _save_remember_login(remember)
                    log.info("Вход выполнен, cookie сохранён")
                    _try_save_cm_refresh_token()
                    return {c["name"]: c["value"] for c in raw}
                time.sleep(2)

            log.warning("Время ожидания входа истекло (5 мин)")
            ctx.close()
            browser.close()
    except Exception as e:
        log.error("Ошибка браузера: %s", e)

    return None
