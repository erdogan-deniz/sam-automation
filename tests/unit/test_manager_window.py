"""Тесты _click_refresh — поиск кнопки Refresh в _MainToolStrip SAM.Game."""

from __future__ import annotations

from unittest.mock import MagicMock

import app.sam.manager_window as mw
from app.sam.manager_window import _click_refresh, process_game


def _button(cls: str, text: str) -> MagicMock:
    b = MagicMock()
    b.friendly_class_name.return_value = cls
    b.window_text.return_value = text
    return b


def _toolbar(aid: str, *buttons: MagicMock) -> MagicMock:
    tb = MagicMock()
    tb.automation_id.return_value = aid
    tb.children.return_value = list(buttons)
    return tb


def _window(*top_level: MagicMock) -> MagicMock:
    win = MagicMock()
    win.children.return_value = list(top_level)
    return win


def test_click_refresh_finds_and_clicks_refresh_button():
    btn = _button("Button", "Refresh")
    toolbar = _toolbar("_MainToolStrip", _button("Button", "Reset"), btn)
    win = _window(_toolbar("_OtherStrip"), toolbar)

    assert _click_refresh(win) is True
    btn.click_input.assert_called_once()


def test_click_refresh_false_when_toolbar_has_no_refresh():
    toolbar = _toolbar("_MainToolStrip", _button("Button", "Reset"))
    assert _click_refresh(_window(toolbar)) is False


def test_click_refresh_false_when_no_main_toolstrip():
    assert _click_refresh(_window(_toolbar("_OtherStrip"))) is False


def test_click_refresh_false_on_exception():
    win = MagicMock()
    win.children.side_effect = RuntimeError("UIA сломан")
    assert _click_refresh(win) is False


def test_refresh_recheck_uses_short_timeout(monkeypatch):
    app = MagicMock()
    app.windows.return_value = [MagicMock()]
    timeouts: list[float] = []

    def fake_check(_win, timeout):
        timeouts.append(timeout)
        return ("retry", 0)

    monkeypatch.setattr(mw, "_check_game_status", fake_check)
    monkeypatch.setattr(mw, "_click_refresh", lambda _w: True)

    result = process_game(app, 123, load_timeout=20)

    assert result.skipped and result.skip_reason == "retry"
    # 1-я проверка — полный load_timeout, 2-я (после Refresh) — короткая
    assert timeouts == [20, mw._REFRESH_RECHECK_TIMEOUT]
    assert mw._REFRESH_RECHECK_TIMEOUT < 20
