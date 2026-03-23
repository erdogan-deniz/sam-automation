"""Win32 API утилиты для работы с процессами и окнами SAM.

Низкоуровневый слой — только ctypes, никаких pywinauto-зависимостей.
Используется из app.sam.launcher для обнаружения/завершения SAM.Game.exe
и управления modal-диалогами SAM.Picker.exe.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

log = logging.getLogger("sam_automation")

# ---------------------------------------------------------------------------
#  Win32 дескрипторы и константы
# ---------------------------------------------------------------------------

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32

_TH32CS_SNAPPROCESS = 0x00000002
_GW_ENABLEDPOPUP = 6
_WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)


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


# ---------------------------------------------------------------------------
#  Управление процессами
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
#  Управление окнами
# ---------------------------------------------------------------------------


def _is_window_enabled(hwnd: int) -> bool:
    """Проверяет, не заблокировано ли окно (например, modal-диалогом)."""
    return bool(_user32.IsWindowEnabled(hwnd))


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


def _close_picker_modal(
    picker_hwnd: int, picker_pid: int, wait_timeout: float = 3.0
) -> bool:
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
        if _is_window_enabled(picker_hwnd):
            break
    return True
