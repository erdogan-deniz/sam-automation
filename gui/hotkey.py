"""Глобальный горячий клавиш через WH_KEYBOARD_LL (без новых зависимостей)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
HC_ACTION = 0

# Virtual key codes
VK_F10 = 0x79
VK_ESCAPE = 0x1B

_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulong),
    ]


class GlobalHotkey:
    """Глобальный хук клавиатуры — перехватывает нажатие до любого окна.

    Использование:
        hk = GlobalHotkey(VK_ESCAPE, callback)
        # ...
        hk.unregister()
    """

    def __init__(self, vk: int, callback: Callable[[], None]) -> None:
        self._vk = vk
        self._callback = callback
        self._hook: ctypes.c_void_p | None = None
        self._active = False
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        def _proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode == HC_ACTION and wParam == WM_KEYDOWN:
                kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == self._vk:
                    self._callback()
            return _user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._hook_proc = _HOOKPROC(_proc)  # удерживаем ссылку — иначе GC удалит
        self._hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            _kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            return

        self._active = True
        msg = ctypes.wintypes.MSG()
        while self._active and _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def unregister(self) -> None:
        """Снимает хук клавиатуры."""
        self._active = False
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
