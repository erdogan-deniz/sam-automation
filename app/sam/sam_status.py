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


def _find_child(parent, automation_id: str):
    """Первый прямой child с данным automation_id (или None).

    ВАЖНО: только children() — у UIAWrapper (app.windows()[0]) НЕТ метода
    child_window (он есть лишь у WindowSpecification); descendants() на
    зависшем окне занимает ~5с. Битые контролы пропускаем.
    """
    try:
        kids = parent.children()
    except Exception:
        return None
    for child in kids:
        try:
            if child.automation_id() == automation_id:
                return child
        except Exception:
            continue
    return None


def _read_achievement_count(game_window) -> int | None:
    """Число строк (ListItem) в _AchievementListView.

    Путь по дереву окна (см. дамп scripts/diag/dump_sam_window.py):
    Manager → _MainTabControl → _AchievementsTabPage → _AchievementListView.

    Returns:
        int  — список найден (0 = пуст / нет достижений)
        None — контролы ещё не построились / UIA-ошибка (окно грузится)
    """
    tab = _find_child(game_window, "_MainTabControl")
    if tab is None:
        return None
    page = _find_child(tab, "_AchievementsTabPage")
    if page is None:
        return None
    listview = _find_child(page, _ACHIEVEMENT_LIST_ID)
    if listview is None:
        return None
    try:
        count = 0
        for child in listview.children():
            try:
                if child.friendly_class_name() == "ListItem":
                    count += 1
            except Exception:
                continue
        return count
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
        "no achievements" — SAM сообщил 'Retrieved 0 achievements' —
                            единственный прямой сигнал «нет достижений»
        "error"           — SAM показал error в статус-баре: часто транзиент
                            (Steam/сеть) — caller даёт Refresh-шанс; финально
                            игра идёт в error.txt (retryable), НЕ в without
        "retry"           — список так и не заполнился за timeout (временно;
                            process_game даёт Refresh-шанс, затем error)

    Готовность = число строк в _AchievementListView стабильно >= settle
    секунд. Если к дедлайну список непуст, но не стабилизировался — берём
    как есть: Unlock All работает по фактически загруженному списку.
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
                return "error", 0
            match = re.search(r"retrieved\s+(\d+)", text)
            if match and int(match.group(1)) == 0:
                return "no achievements", 0
            last_count = -1  # сброс стабилизации, если список «мигнул» в 0

        time.sleep(0.1)

    if last_count > 0:
        # Список есть, просто не успел «устаканиться» — не выбрасываем факт
        log.debug(
            "Список не стабилизировался за %.0fс — беру %d как есть",
            timeout,
            last_count,
        )
        return None, last_count

    # Не загрузилось за timeout — отдаём в retry (caller сделает Refresh)
    return "retry", 0
