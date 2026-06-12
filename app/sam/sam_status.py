"""Детект достижений в окне SAM.Game по списку _AchievementListView.

Источник истины — заполненность списка достижений (структурный контрол),
а не текст статус-бара: статус-бар появляется с задержкой и раньше ронял
медленные игры в ложный ERROR. Статус-бар используется лишь для быстрого
выхода «нет достижений» (Retrieved 0 / error), чтобы не ждать впустую.
"""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("sam_automation")

# automation_id списка достижений в окне SAM.Game (вкладка Achievements).
_ACHIEVEMENT_LIST_ID = "_AchievementListView"


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


def _read_achievement_count(game_window) -> int | None:
    """Число строк (ListItem) в _AchievementListView.

    Returns:
        int  — список найден (0 = пуст / ещё не загружен / нет достижений)
        None — контрол ещё не готов / UIA-ошибка (окно грузится)
    """
    try:
        listview = game_window.child_window(auto_id=_ACHIEVEMENT_LIST_ID)
        return sum(
            1
            for child in listview.children()
            if child.friendly_class_name() == "ListItem"
        )
    except Exception:
        return None


def _check_game_status(
    game_window,
    timeout: float = 20.0,
    settle: float = 1.0,
) -> tuple[str | None, int]:
    """Ждёт загрузки списка достижений. Возвращает (skip_reason | None, count).

    skip_reason:
        None              — достижения загружены (count = сколько строк)
        "no achievements" — SAM сообщил 'Retrieved 0' или 'error'
        "retry"           — список так и не заполнился за timeout (временно;
                            process_game даёт Refresh-шанс, затем error)

    Готовность = число строк в _AchievementListView стабильно >= settle
    секунд (загрузка завершилась). Пустой список + статус 'Retrieved 0' /
    'error' → нет достижений (быстрый выход). Пустой список без статуса →
    ещё грузится, ждём дальше.
    """
    deadline = time.time() + timeout
    last_count = -1
    stable_since = 0.0

    while time.time() < deadline:
        count = _read_achievement_count(game_window)

        if count and count > 0:
            if count != last_count:
                last_count = count
                stable_since = time.time()
            elif time.time() - stable_since >= settle:
                return None, count
        else:
            # Список пуст/не готов — быстрый выход по статус-бару
            text = _read_status_panel(game_window)
            if "error" in text:
                return "no achievements", 0
            match = re.search(r"retrieved\s+(\d+)", text)
            if match and int(match.group(1)) == 0:
                return "no achievements", 0
            last_count = -1  # сброс стабилизации, если список «мигнул» в 0

        time.sleep(0.1)

    # Не загрузилось за timeout — отдаём в retry (caller сделает Refresh)
    return "retry", 0
