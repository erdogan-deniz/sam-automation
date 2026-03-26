"""Глобальный горячий клавиш через Windows RegisterHotKey (без новых зависимостей)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable

_WM_HOTKEY = 0x0312
_user32 = ctypes.windll.user32

# Virtual key codes
VK_F10 = 0x79


class GlobalHotkey:
    """Системный хоткей — срабатывает даже без фокуса на окне.

    Использование:
        hk = GlobalHotkey(VK_F10, callback)
        # ...
        hk.unregister()
    """

    def __init__(self, vk: int, callback: Callable[[], None]) -> None:
        self._vk = vk
        self._callback = callback
        self._id = id(self) & 0xBFFF  # Windows hotkey ID (1–0xBFFF)
        self._active = False
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        if not _user32.RegisterHotKey(None, self._id, 0, self._vk):
            return
        self._active = True
        msg = ctypes.wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == _WM_HOTKEY and msg.wParam == self._id:
                self._callback()

    def unregister(self) -> None:
        """Отменяет регистрацию хоткея."""
        if self._active:
            _user32.UnregisterHotKey(None, self._id)
            self._active = False
