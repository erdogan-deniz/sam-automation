"""Извлечение Steam Community кук через Playwright (headless + visible login)."""

from __future__ import annotations

import logging
import time

from app.auth import _JWT_REFRESH_FILE, _jwt_web_cookies, _load_session

from .storage import _save_manual_cookie, _save_remember_login

log = logging.getLogger("sam_automation")


def _try_save_cm_refresh_token() -> None:
    """После браузерного входа сохраняет CM JWT refresh_token для автоматизации scan.py."""
    if _JWT_REFRESH_FILE.exists():
        return

    saved = _load_session()
    if not saved:
        return

    username, password = saved

    print(
        "\n[Steam] scan.py тоже может работать без 2FA — нужно ввести код один раз."
    )
    answer = (
        input("[Steam] Настроить автоматический вход для scan.py? [y/N]: ")
        .strip()
        .lower()
    )
    if answer not in ("y", "yes", "д", "да"):
        return

    log.info("Получаю CM JWT refresh_token для автоматизации scan.py...")
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
            browser = pw.chromium.launch(
                headless=False, args=["--start-maximized"]
            )
            # try/finally: гарантируем закрытие браузера, даже если goto/чтение
            # кук/сохранение бросят между launch и явным close — иначе видимое
            # окно Chromium утекает вплоть до выхода из sync_playwright.
            try:
                ctx = browser.new_context(no_viewport=True)
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
                        # Закрываем ДО интерактивного CM-промпта, чтобы окно
                        # не висело; finally повторно закроет (идемпотентно).
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
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        log.error("Ошибка браузера: %s", e)

    return None
