"""Тесты _click_refresh — поиск и нажатие кнопки Refresh в SAM.Game."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.sam.manager_window import _click_refresh


def _button(cls: str, text: str) -> MagicMock:
    b = MagicMock()
    b.friendly_class_name.return_value = cls
    b.window_text.return_value = text
    return b


def test_click_refresh_finds_and_clicks_refresh_button():
    btn = _button("Button", "Refresh")
    win = MagicMock()
    win.descendants.return_value = [_button("Button", "Commit"), btn]

    assert _click_refresh(win) is True
    btn.click_input.assert_called_once()


def test_click_refresh_false_when_no_refresh_button():
    win = MagicMock()
    win.descendants.return_value = [_button("Button", "Commit Changes")]

    assert _click_refresh(win) is False


def test_click_refresh_false_on_exception():
    win = MagicMock()
    win.descendants.side_effect = RuntimeError("UIA сломан")

    assert _click_refresh(win) is False
