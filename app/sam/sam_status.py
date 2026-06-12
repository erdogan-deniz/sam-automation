"""Чтение и классификация статус-бара SAM.Game (ToolStripStatusLabel)."""

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


def _check_game_status(
    game_window,
    timeout: float = 3.0,
    settle: float = 1.0,
    empty_grace: float = 8.0,
) -> tuple[str | None, int]:
    """Опрашивает статус-бар SAM.Game. Возвращает (skip_reason | None, count).

    skip_reason:
        None              — OK, достижения загружены (count = сколько)
        "no achievements" — у игры нет достижений / SAM показал Error
        "retry"           — статистику не удалось прочитать (грузилась, но не
                            успела за timeout; ИЛИ статус-бар пуст за
                            empty_grace). И то и другое временно — игре нужно
                            дать Refresh-шанс (делает process_game). Медленная
                            игра с достижениями первые секунды тоже пуста,
                            поэтому НЕ откидываем её сразу в error.

    SAM проходит транзит: 'Retrieving...' → 'Error...' → 'X achievements'.
    Стабильным считаем текст, не менявшийся >= settle секунд.
    """
    deadline = time.time() + timeout
    empty_deadline = time.time() + empty_grace
    saw_loading = False
    last = ""
    stable_since = 0.0

    while time.time() < deadline:
        text = _read_status_panel(game_window)

        if text.startswith(_LOADING_TEXT):
            saw_loading = True
            last = ""
        elif text:
            if text != last:
                last = text
                stable_since = time.time()
            elif time.time() - stable_since >= settle:
                if "retrieved" in last:
                    match = re.search(r"(\d+)", last)
                    return None, int(match.group(1)) if match else 0
                if "error" in last:
                    return "no achievements", 0
                return "retry", 0  # неизвестный стабильный текст

        # Статус пуст и загрузка не началась за empty_grace: либо битая игра,
        # либо медленная с достижениями. Не решаем здесь — отдаём в retry,
        # чтобы process_game дал Refresh-шанс (битая останется пустой → error).
        if not saw_loading and not last and time.time() > empty_deadline:
            log.debug("Статус-бар пуст за %.1fs — пробую Refresh", empty_grace)
            return "retry", 0

        time.sleep(0.1)

    # Таймаут: статистика грузилась, но финала не дождались → временно
    return "retry", 0
