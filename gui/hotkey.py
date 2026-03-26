"""Глобальный горячий клавиш через Windows RegisterHotKey (без новых зависимостей)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from collections.abc import Callable

_WM_HOTKEY = 0x0312
_PM_REMOVE = 0x0001
_user32 = ctypes.windll.user32

# Virtual key codes
VK_F10 = 0x79
VK_ESCAPE = 0x1B

_hotkey_counter = 0
_hotkey_lock = threading.Lock()


def _next_id() -> int:
    global _hotkey_counter
    with _hotkey_lock:
        _hotkey_counter += 1
        return _hotkey_counter


class GlobalHotkey:
    """Системный хоткей — срабатывает даже без фокуса на окне.

    Использование:
        hk = GlobalHotkey(VK_ESCAPE, callback)
        # ...
        hk.unregister()
    """

    def __init__(self, vk: int, callback: Callable[[], None]) -> None:
        self._vk = vk
        self._callback = callback
        self._id = _next_id()
        self._active = False
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        if not _user32.RegisterHotKey(None, self._id, 0, self._vk):
            return
        self._active = True
        msg = ctypes.wintypes.MSG()
        while self._active:
            # PeekMessageW не блокирует — работает надёжно в daemon-потоке
            if _user32.PeekMessageW(ctypes.byref(msg), None, _WM_HOTKEY, _WM_HOTKEY, _PM_REMOVE):
                if msg.message == _WM_HOTKEY and msg.wParam == self._id:
                    self._callback()
            time.sleep(0.05)

    def unregister(self) -> None:
        """Отменяет регистрацию хоткея."""
        self._active = False
        _user32.UnregisterHotKey(None, self._id)
