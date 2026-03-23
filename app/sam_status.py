"""Чтение и ожидание статус-бара SAM.Game (ToolStripStatusLabel)."""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("sam_automation")

_LOADING_TEXT = "retrieving stat information"


def _read_status_panel(game_window) -> str:
    """Читает текст из панелей StatusBar (ToolStripStatusLabel), lowercase."""
    for ctrl in game_window.children():
        try:
            if ctrl.friendly_class_name() != "StatusBar":
                continue
            text = ctrl.window_text().strip()
            if text:
                return text.lower()
            for panel in ctrl.children():
                try:
                    text = panel.window_text().strip()
                    if text:
                        return text.lower()
                except Exception:
                    pass
        except Exception:
            pass
    return ""


def _wait_for_status(
    game_window, timeout: float = 8.0, settle: float = 0.5
) -> str:
    """Ждёт стабильного финального состояния статус-бара, возвращает lowercase.

    SAM проходит через транзитные состояния: 'Retrieving...' → 'Error...' → 'X achievements'.
    Возвращает текст только когда он не менялся >= settle секунд подряд.
    Если за timeout так и не стабилизировался — возвращает последний виденный текст.
    """
    deadline = time.time() + timeout
    last = ""
    stable_since: float = 0.0

    while time.time() < deadline:
        text = _read_status_panel(game_window)
        if text and not text.startswith(_LOADING_TEXT):
            if text != last:
                last = text
                stable_since = time.time()
            elif time.time() - stable_since >= settle:
                log.debug("Статус-бар (стабильный): %r", text)
                return last
        time.sleep(0.1)

    log.debug(
        "Статус-бар не стабилизировался за %.1fs, последний: %r", timeout, last
    )
    return last


def _check_game_status(
    game_window, timeout: float = 3.0
) -> tuple[str | None, int]:
    """Читает статус-бар SAM.Game. Возвращает (skip_reason | None, achievement_count).

    skip_reason:
        None             — OK, достижения загружены
        "no achievements" — у игры нет достижений (постоянный пропуск)
        "error"          — SAM не смог загрузить достижения (временная ошибка, можно повторить)
    """
    status = _wait_for_status(game_window, timeout=timeout, settle=1.0)
    if "error" in status:
        return "no achievements", 0
    if "retrieved" in status:
        match = re.search(r"(\d+)", status)
        count = int(match.group(1)) if match else 0
        return None, count
    return "error", 0
