"""Тесты _close_picker_modal: диалог SAM.Picker закрывается и Picker оживает.

Живой прогон 21.10.2026: после диалога на appid 5 BM_CLICK по первой кнопке
Picker не оживил, и все следующие игры падали. Теперь, если кнопка не помогла,
диалогу шлётся WM_CLOSE.
"""

from __future__ import annotations

import pytest

import app.sam.win32_utils as wu

_PICKER, _POPUP = 10, 20


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class _User32:
    def __init__(self, *, popup: int = _POPUP) -> None:
        self._popup = popup
        self.posted: list[tuple[int, int]] = []

    def GetWindow(self, hwnd: int, cmd: int) -> int:
        return self._popup

    def PostMessageW(
        self, hwnd: int, msg: int, wparam: int, lparam: int
    ) -> int:
        self.posted.append((hwnd, msg))
        return 1


def _setup(monkeypatch, *, button_closes: bool, close_closes: bool):  # type: ignore[no-untyped-def]
    state = {"open": True}
    user32 = _User32()

    def _post(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        user32.posted.append((hwnd, msg))
        if close_closes:
            state["open"] = False
        return 1

    user32.PostMessageW = _post  # type: ignore[method-assign]

    def _click(hwnd: int) -> bool:
        if button_closes:
            state["open"] = False
        return True

    clock = _Clock()
    monkeypatch.setattr(wu, "_user32", user32)
    monkeypatch.setattr(wu, "_click_first_button", _click)
    monkeypatch.setattr(wu, "_is_window_enabled", lambda h: not state["open"])
    monkeypatch.setattr(wu, "_window_title", lambda h: "Error")
    monkeypatch.setattr(wu, "_dialog_text", lambda h: "")
    monkeypatch.setattr(wu.time, "time", clock.time)
    monkeypatch.setattr(wu.time, "sleep", clock.sleep)
    return user32, state


def test_button_closes_dialog_no_wm_close(monkeypatch: pytest.MonkeyPatch):
    user32, state = _setup(monkeypatch, button_closes=True, close_closes=True)
    assert wu._close_picker_modal(_PICKER, 1) == ""
    assert not state["open"]
    assert user32.posted == []


def test_wm_close_when_button_did_not_help(monkeypatch: pytest.MonkeyPatch):
    user32, state = _setup(monkeypatch, button_closes=False, close_closes=True)
    assert wu._close_picker_modal(_PICKER, 1) == ""
    assert user32.posted == [(_POPUP, wu._WM_CLOSE)]
    assert not state["open"]


def test_no_dialog_returns_false(monkeypatch: pytest.MonkeyPatch):
    _setup(monkeypatch, button_closes=True, close_closes=True)
    monkeypatch.setattr(wu, "_user32", _User32(popup=0))
    monkeypatch.setattr(wu, "_find_picker_dialog", lambda pid, main: 0)
    assert wu._close_picker_modal(_PICKER, 1) is None


def test_returns_dialog_text(monkeypatch: pytest.MonkeyPatch):
    # По тексту вызывающий отличает «нет в библиотеке» от прочих отказов.
    _setup(monkeypatch, button_closes=True, close_closes=True)
    monkeypatch.setattr(
        wu, "_dialog_text", lambda h: "You don't own that game."
    )
    assert wu._close_picker_modal(_PICKER, 1) == "You don't own that game."


class _DialogUser32:
    """Дети диалога: (hwnd, класс, текст) — как у Win32 MessageBox."""

    def __init__(self, children: list[tuple[int, str, str]]) -> None:
        self._kids = {h: (cls, txt) for h, cls, txt in children}

    def EnumChildWindows(self, hwnd: int, cb, lparam: int) -> int:  # type: ignore[no-untyped-def]
        for child in self._kids:
            cb(child, lparam)
        return 1

    def GetClassNameW(self, hwnd: int, buf, n: int) -> int:  # type: ignore[no-untyped-def]
        buf.value = self._kids[hwnd][0]
        return len(buf.value)

    def GetWindowTextW(self, hwnd: int, buf, n: int) -> int:  # type: ignore[no-untyped-def]
        buf.value = self._kids[hwnd][1]
        return len(buf.value)


def test_dialog_text_reads_static_children_not_buttons(
    monkeypatch: pytest.MonkeyPatch,
):
    # Заголовок «Error» причины не говорит — текст лежит в Static-детях.
    monkeypatch.setattr(
        wu,
        "_user32",
        _DialogUser32(
            [
                (1, "Static", ""),
                (2, "Static", "You don't own the game."),
                (3, "Button", "OK"),
            ]
        ),
    )
    monkeypatch.setattr(wu, "_WNDENUMPROC", lambda f: f)
    assert wu._dialog_text(_POPUP) == "You don't own the game."
