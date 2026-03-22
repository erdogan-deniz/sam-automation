"""Запуск SAM.Picker.exe, добавление игр и открытие окна достижений."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import time
from pathlib import Path

from pywinauto import Application, mouse, keyboard

from .exceptions import SAMConnectionError, SAMLaunchError, SAMGameError

log = logging.getLogger("sam_automation")

# ---------------------------------------------------------------------------
#  Быстрый поиск PID через Win32 API (вместо subprocess tasklist)
# ---------------------------------------------------------------------------

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32
_TH32CS_SNAPPROCESS = 0x00000002
_GW_ENABLEDPOPUP = 6
_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _get_sam_game_pids() -> set[int]:
    """PID всех SAM.Game.exe — через Win32 API (<1мс вместо ~100мс tasklist)."""
    snap = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return set()
    pe = _PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    pids: set[int] = set()
    try:
        if _kernel32.Process32First(snap, ctypes.byref(pe)):
            while True:
                if pe.szExeFile.lower() == b"sam.game.exe":
                    pids.add(pe.th32ProcessID)
                if not _kernel32.Process32Next(snap, ctypes.byref(pe)):
                    break
    finally:
        _kernel32.CloseHandle(snap)
    return pids


def _kill_pid(pid: int) -> None:
    """Убивает процесс по PID через Win32 API и ждёт завершения."""
    PROCESS_TERMINATE = 0x0001
    SYNCHRONIZE = 0x00100000
    handle = _kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if handle:
        _kernel32.TerminateProcess(handle, 1)
        _kernel32.WaitForSingleObject(handle, 500)  # ждём до 500мс
        _kernel32.CloseHandle(handle)


def _click_first_button(hwnd: int) -> bool:
    """Находит первую кнопку-потомок окна и кликает через BM_CLICK (без захвата фокуса)."""
    found: list[int] = []
    buf = ctypes.create_unicode_buffer(64)

    def _cb(child: int, _: int) -> bool:
        _user32.GetClassNameW(child, buf, 64)
        if "button" in buf.value.lower():
            found.append(child)
        return True

    _user32.EnumChildWindows(hwnd, _WNDENUMPROC(_cb), 0)
    if found:
        _user32.SendMessageW(found[0], 0x00F5, 0, 0)  # BM_CLICK
        log.debug("BM_CLICK → hwnd=%d (кнопка=%d)", hwnd, found[0])
        return True
    return False


def _find_picker_dialog(picker_pid: int, main_hwnd: int) -> int:
    """Ищет любое видимое top-level окно процесса Picker, кроме главного."""
    found: list[int] = []
    pid_buf = ctypes.wintypes.DWORD()

    def _cb(hwnd: int, _: int) -> bool:
        if _user32.IsWindowVisible(hwnd) and hwnd != main_hwnd:
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
            if pid_buf.value == picker_pid:
                found.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    if found:
        log.debug("EnumWindows нашёл окна Picker: %s", found)
    return found[0] if found else 0


def _close_picker_modal(picker_hwnd: int, picker_pid: int, wait_timeout: float = 3.0) -> bool:
    """Ищет и закрывает modal dialog Picker. Возвращает True если диалог был закрыт.

    После клика ждёт пока Picker снова станет enabled (до wait_timeout секунд).
    """
    popup = _user32.GetWindow(picker_hwnd, _GW_ENABLEDPOPUP)
    if not popup or popup == picker_hwnd:
        popup = _find_picker_dialog(picker_pid, picker_hwnd)
    if not popup:
        return False
    log.debug("Modal диалог SAM найден: hwnd=%d", popup)
    _click_first_button(popup)
    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        time.sleep(0.05)
        if _user32.IsWindowEnabled(picker_hwnd):
            break
    return True


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
        for c in self.toolbar.children():
            cls = c.friendly_class_name()
            if cls == "Edit" and self._edit is None:
                self._edit = c
            elif cls == "Button" and "add" in c.window_text().lower():
                self._add_btn = c

    def add_and_open_game(self, game_id: int, timeout: float = 10.0) -> Application:
        """Ввод ID → Add Game → двойной клик → ждём SAM.Game."""
        self.win.set_focus()
        picker_hwnd = self.win.wrapper_object().handle  # кэшируем пока Picker активен

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
            if not _user32.IsWindowEnabled(picker_hwnd):
                log.debug("Picker disabled — ищем modal dialog")
                dialog_closed = _close_picker_modal(picker_hwnd, self.picker_pid)
                break
            try:
                items = [c for c in self._listview.children()
                         if c.friendly_class_name() == "ListItem"]
            except Exception:
                items = []
            if items:
                break

        if not items:
            if not dialog_closed:
                # Диалог мог появиться после цикла — даём ещё 2с
                try:
                    deadline_dialog = time.time() + 2.0
                    while time.time() < deadline_dialog:
                        time.sleep(0.1)
                        if not _user32.IsWindowEnabled(picker_hwnd):
                            _close_picker_modal(picker_hwnd, self.picker_pid)
                            break
                    else:
                        log.debug("Диалог не появился за 2с")
                except Exception:
                    log.exception("Ошибка при закрытии диалога SAM")

            # Перепроверяем список после закрытия диалога
            try:
                items = [c for c in self._listview.children()
                         if c.friendly_class_name() == "ListItem"]
            except Exception:
                items = []

            if not items:
                raise SAMGameError(game_id, "SAM: игра недоступна")

        # PID'ы до двойного клика (Win32 — <1мс)
        existing_pids = _get_sam_game_pids()

        r = items[0].rectangle()
        mouse.double_click(coords=(r.left + (r.right - r.left) // 2,
                                   r.top + (r.bottom - r.top) // 2))

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
            raise SAMGameError(game_id, f"Процесс SAM.Game не появился за {timeout}с")

        # Шаг 2: connect + ждём окно
        log.info("[%d] SAM.Game PID=%d", game_id, found_pid)
        game_app = Application(backend="uia").connect(process=found_pid, timeout=5)
        while time.time() < deadline:
            try:
                wins = game_app.windows()
                if wins:
                    return game_app
            except Exception:
                pass
            time.sleep(0.03)

        raise SAMGameError(game_id, "Окно Manager не появилось")


def close_game(game_app: Application | None) -> None:
    """Убивает SAM.Game по PID через Win32 API. Не трогает Picker."""
    if game_app is None:
        return
    try:
        _kill_pid(game_app.process)
    except Exception:
        pass


def launch_picker(exe_path: str, launch_delay: float = 10.0) -> tuple[subprocess.Popen, PickerSession]:
    """Запускает SAM.Picker.exe, подключается и создаёт PickerSession."""
    exe = Path(exe_path)
    picker = exe.parent / "SAM.Picker.exe"
    if not picker.exists():
        raise SAMLaunchError(f"SAM.Picker.exe не найден: {picker}")

    log.info("Запуск SAM.Picker.exe ...")

    try:
        proc = subprocess.Popen([str(picker)], cwd=str(picker.parent))
    except OSError as e:
        raise SAMLaunchError(f"Не удалось запустить SAM.Picker.exe: {e}") from e

    deadline = time.time() + launch_delay
    last_error: Exception | None = None

    while time.time() < deadline:
        if proc.poll() is not None:
            raise SAMLaunchError(f"SAM.Picker.exe завершился с кодом {proc.returncode}")
        try:
            app = Application(backend="uia").connect(process=proc.pid, timeout=1)
            win = app.top_window()
            win.wait("visible", timeout=2)
            session = PickerSession(app)
            log.info("SAM.Picker.exe подключён (PID=%d)", proc.pid)
            return proc, session
        except Exception as e:
            last_error = e
            time.sleep(0.3)

    if proc.poll() is not None:
        raise SAMLaunchError(f"SAM.Picker.exe завершился с кодом {proc.returncode}")
    proc.kill()
    raise SAMConnectionError(f"Не удалось подключиться к SAM.Picker.exe: {last_error}")


def kill_process(proc: subprocess.Popen) -> None:
    """Принудительно завершает процесс."""
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
