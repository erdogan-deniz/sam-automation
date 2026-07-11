"""Тесты win32_utils: корректность HANDLE (restype) и sentinel снапшота.

HANDLE на 64-битной Windows шире 32 бит. Без явного restype=HANDLE ctypes
трактует возврат как c_int (32-бит) и обрезает дескриптор — тот же класс
ловушки, что dpapi.py документирует и лечит (restype=wt.HANDLE).
"""

from __future__ import annotations

import ctypes.wintypes as wt

import app.sam.win32_utils as wu


def test_snapshot_and_openprocess_have_handle_restype() -> None:
    # Регресс-гард: обе функции, возвращающие HANDLE, должны иметь restype=HANDLE.
    assert wu._kernel32.CreateToolhelp32Snapshot.restype is wt.HANDLE
    assert wu._kernel32.OpenProcess.restype is wt.HANDLE


def test_get_sam_game_pids_empty_on_invalid_snapshot(monkeypatch) -> None:
    # Провал снапшота (INVALID_HANDLE_VALUE) → пустой набор, без падения и
    # дальнейших win32-вызовов по битому дескриптору.
    monkeypatch.setattr(
        wu._kernel32,
        "CreateToolhelp32Snapshot",
        lambda *a: wu._INVALID_HANDLE,
    )
    assert wu._get_sam_game_pids() == set()
