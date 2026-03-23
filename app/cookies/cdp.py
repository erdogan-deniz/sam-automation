"""Извлечение Steam Community кук через Chrome DevTools Protocol (CDP)."""

from __future__ import annotations

import logging

from .storage import _jwt_expired

log = logging.getLogger("sam_automation")


def _cdp_steam_cookies() -> dict | None:
    """Подключается к запущенному браузеру через CDP (Chrome DevTools Protocol).

    Ищет --remote-debugging-port=XXXX в командной строке всех Chromium-процессов
    через psutil. Если находит — читает steamcommunity.com куки напрямую,
    минуя файловые блокировки и шифрование SQLite.

    Требует запуска браузера с флагом --remote-debugging-port=XXXX.
    """
    try:
        import psutil
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    port: int | None = None
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            if not any(
                b in name for b in ("browser.exe", "chrome.exe", "msedge.exe")
            ):
                continue
            for arg in cmdline:
                if isinstance(arg, str) and arg.startswith(
                    "--remote-debugging-port="
                ):
                    p = arg.split("=", 1)[1]
                    if p.isdigit() and int(p) > 0:
                        port = int(p)
                        break
            if port:
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not port:
        return None

    log.debug("CDP: найден remote-debugging-port=%d", port)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(
                f"http://localhost:{port}", timeout=5_000
            )
            for ctx in browser.contexts:
                raw = ctx.cookies("https://steamcommunity.com")
                cookies = {c["name"]: c["value"] for c in raw}
                val = cookies.get("steamLoginSecure", "")
                if val and "||" in val and not _jwt_expired(val):
                    log.info("CDP: JWT cookie получен (порт %d)", port)
                    browser.close()
                    return cookies
            browser.close()
    except Exception as e:
        log.debug("CDP порт %d: %s", port, e)

    return None
