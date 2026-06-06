"""Тесты _check_game_status — классификация статус-бара SAM.Game.

Используются малые settle/empty_grace, чтобы тесты были быстрыми.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import app.sam.sam_status as ss
from app.sam.sam_status import _check_game_status


def _fixed_status(monkeypatch, text: str):
    monkeypatch.setattr(ss, "_read_status_panel", lambda _w: text)


def test_empty_status_returns_error_early(monkeypatch):
    # Пустой статус, загрузка не началась → error через empty_grace (быстро)
    _fixed_status(monkeypatch, "")
    assert _check_game_status(
        MagicMock(), timeout=2.0, empty_grace=0.2, settle=0.1
    ) == ("error", 0)


def test_loading_then_timeout_returns_retry(monkeypatch):
    # Статистика грузится ('retrieving'), но не успевает за timeout → retry
    _fixed_status(monkeypatch, "retrieving stat information for app 123")
    assert _check_game_status(
        MagicMock(), timeout=0.5, empty_grace=5.0, settle=0.1
    ) == ("retry", 0)


def test_retrieved_returns_count(monkeypatch):
    _fixed_status(monkeypatch, "12 achievements retrieved")
    assert _check_game_status(
        MagicMock(), timeout=2.0, empty_grace=1.0, settle=0.1
    ) == (None, 12)


def test_error_status_returns_no_achievements(monkeypatch):
    _fixed_status(monkeypatch, "error: no stats")
    assert _check_game_status(
        MagicMock(), timeout=2.0, empty_grace=1.0, settle=0.1
    ) == ("no achievements", 0)
