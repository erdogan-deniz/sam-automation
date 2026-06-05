"""Реальный тест _has_error_window — детект окна 'Error' SAM.Game.exe.

Не мок: создаёт настоящее tkinter-окно с заголовком 'Error' и проверяет,
что win32-детект (EnumWindows) его находит по PID текущего процесса.
"""

from __future__ import annotations

import os
import tkinter as tk

import pytest

from app.sam.win32_utils import _has_error_window


def _make_window(title: str) -> tk.Tk:
    root = tk.Tk()
    root.title(title)
    root.geometry("120x60+0+0")
    root.update_idletasks()
    root.update()  # отрисовать → окно становится видимым для EnumWindows
    return root


def test_has_error_window_detects_real_error_titled_window():
    try:
        root = _make_window("Error")
    except tk.TclError:
        pytest.skip("Нет дисплея для tkinter")
    try:
        assert _has_error_window(os.getpid()) is True
    finally:
        root.destroy()


def test_has_error_window_false_for_other_title():
    try:
        root = _make_window("Boost Playtime")
    except tk.TclError:
        pytest.skip("Нет дисплея для tkinter")
    try:
        assert _has_error_window(os.getpid()) is False
    finally:
        root.destroy()


def test_has_error_window_false_for_foreign_pid():
    # PID без окон 'Error' (текущий процесс без созданного окна) → False
    assert _has_error_window(os.getpid()) is False
