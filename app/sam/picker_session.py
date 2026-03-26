"""Сессия SAM.Picker.exe — кэширует окно и управляет добавлением игр."""

from __future__ import annotations

import logging
import time

from pywinauto import Application, mouse

from ..exceptions import SAMGameError
from .win32_utils import (
    _close_picker_modal,
    _get_sam_game_pids,
    _is_window_enabled,
)

log = logging.getLogger("sam_automation")


class PickerSession:
    """Кэширует Picker окно и все его элементы на весь процесс."""

    def __init__(self, app: Application) -> None:
        self.app = app
        self.win = app.window(auto_id="GamePicker")
        self.win.wait("exists", timeout=5)
        self.picker_pid = self.win.process_id()

        self.toolbar = self.win.child_window(auto_id="_PickerToolStrip")
        self._edit = None
        self._add_btn = None
        self._listview = self.win.child_window(auto_id="_GameListView")
        self._cache_toolbar_controls()

    def _cache_toolbar_controls(self) -> None:
        """Сканирует дочерние элементы тулбара и кэширует Edit и кнопку Add."""
        for c in self.toolbar.children():
            cls = c.friendly_class_name()
            if cls == "Edit" and self._edit is None:
                self._edit = c
            elif cls == "Button" and "add" in c.window_text().lower():
                self._add_btn = c

    def add_and_open_game(
        self, game_id: int, timeout: float = 10.0
    ) -> Application:
        """Ввод ID → Add Game → двойной клик → ждём SAM.Game."""
        self.win.set_focus()
        picker_hwnd = (
            self.win.wrapper_object().handle
        )  # кэшируем пока Picker активен

        if not self._edit or not self._add_btn:
            raise SAMGameError(game_id, "Элементы Picker не найдены")

        self._edit.set_edit_text(str(game_id))
        self._add_btn.click_input()

        # Ждём появления игры в списке (до 1с).
        # ВАЖНО: проверяем IsWindowEnabled ДО вызова UIA —
        # когда открыт modal dialog, Picker становится disabled и UIA зависает.
        items = []
        dialog_closed = False
        deadline_items = time.time() + 1.0
        while time.time() < deadline_items:
            time.sleep(0.1)
            if not _is_window_enabled(picker_hwnd):
                log.debug("Picker disabled — ищем modal dialog")
                dialog_closed = _close_picker_modal(
                    picker_hwnd, self.picker_pid
                )
                break
            try:
                items = [
                    c
                    for c in self._listview.children()
                    if c.friendly_class_name() == "ListItem"
                ]
            except Exception:
                items = []
            if items:
                break

        # Диалог = SAM отверг игру (например "You don't own the game").
        # Список может содержать предыдущую игру — не трогаем его.
        if dialog_closed:
            raise SAMGameError(game_id, "SAM: ошибка добавления игры")

        if not items:
            # Диалог мог появиться после цикла — даём ещё 2с
            try:
                deadline_dialog = time.time() + 2.0
                while time.time() < deadline_dialog:
                    time.sleep(0.1)
                    if not _is_window_enabled(picker_hwnd):
                        _close_picker_modal(picker_hwnd, self.picker_pid)
                        raise SAMGameError(game_id, "SAM: ошибка добавления игры")
                log.debug("Диалог не появился за 2с")
            except SAMGameError:
                raise
            except Exception:
                log.exception("Ошибка при закрытии диалога SAM")

            # Без диалога и без игры — игра просто недоступна
            try:
                items = [
                    c
                    for c in self._listview.children()
                    if c.friendly_class_name() == "ListItem"
                ]
            except Exception:
                items = []

            if not items:
                raise SAMGameError(game_id, "SAM: игра недоступна")

        # PID'ы до двойного клика (Win32 — <1мс)
        existing_pids = _get_sam_game_pids()

        r = items[0].rectangle()
        mouse.double_click(
            coords=(
                r.left + (r.right - r.left) // 2,
                r.top + (r.bottom - r.top) // 2,
            )
        )

        deadline = time.time() + timeout
        found_pid = None

        # Шаг 1: ждём новый PID (poll каждые 30мс — Win32 API мгновенный)
        while time.time() < deadline:
            time.sleep(0.03)
            new_pids = _get_sam_game_pids() - existing_pids
            if new_pids:
                found_pid = new_pids.pop()
                break

        if found_pid is None:
            raise SAMGameError(
                game_id, f"Процесс SAM.Game не появился за {timeout}с"
            )

        # Шаг 2: connect + ждём окно
        log.info("APP SAM PID: %d", found_pid)
        game_app = Application(backend="uia").connect(
            process=found_pid, timeout=5
        )
        while time.time() < deadline:
            try:
                wins = game_app.windows()
                if wins:
                    return game_app
            except Exception:
                pass
            time.sleep(0.03)

        raise SAMGameError(game_id, "Окно Manager не появилось")
