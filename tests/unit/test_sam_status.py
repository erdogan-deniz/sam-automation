"""Тесты _check_game_status — детект достижений по списку _AchievementListView.

Источник истины — число строк в списке достижений (а не текст статус-бара).
Статус-бар используется только для быстрого выхода «нет достижений»
(Retrieved 0 / error). Оба чтения мокаются, чтобы тесты были быстрыми.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import app.sam.sam_status as ss
from app.sam.sam_status import _check_game_status


def _patch(monkeypatch, *, count, status=""):
    """Мокает чтение списка (count: int|None или callable) и статус-бара."""
    count_fn = count if callable(count) else (lambda _w: count)
    monkeypatch.setattr(ss, "_read_achievement_count", count_fn)
    status_fn = status if callable(status) else (lambda _w: status)
    monkeypatch.setattr(ss, "_read_status_panel", status_fn)


def test_list_with_items_returns_count(monkeypatch):
    # Список заполнен (54 строки) → достижения загружены, count = 54
    _patch(monkeypatch, count=54)
    assert _check_game_status(MagicMock(), timeout=2.0, settle=0.1) == (
        None,
        54,
    )


def test_status_retrieved_zero_is_no_achievements(monkeypatch):
    # Список пуст, статус 'Retrieved 0 achievements' → быстрый выход
    _patch(monkeypatch, count=0, status="retrieved 0 achievements and 5 stats")
    assert _check_game_status(MagicMock(), timeout=2.0, settle=0.1) == (
        "no achievements",
        0,
    )


def test_status_error_is_no_achievements(monkeypatch):
    _patch(monkeypatch, count=0, status="error: failed to retrieve")
    assert _check_game_status(MagicMock(), timeout=2.0, settle=0.1) == (
        "no achievements",
        0,
    )


def test_never_loads_returns_retry(monkeypatch):
    # Список пуст и статус пуст всё время → retry (caller даст Refresh-шанс)
    _patch(monkeypatch, count=0, status="")
    assert _check_game_status(MagicMock(), timeout=0.4, settle=0.1) == (
        "retry",
        0,
    )


def test_control_not_ready_then_loads(monkeypatch):
    # Сначала контрол не готов (None), затем список заполняется → count
    seq = iter([None, None, 12, 12, 12, 12, 12, 12])

    def counts(_w):
        try:
            return next(seq)
        except StopIteration:
            return 12

    _patch(monkeypatch, count=counts, status="")
    assert _check_game_status(MagicMock(), timeout=2.0, settle=0.1) == (
        None,
        12,
    )


def test_count_must_stabilize_before_returning(monkeypatch):
    # Список ещё растёт (10→54): возвращаем только когда стабилизировался
    seq = iter([10, 30, 54, 54, 54, 54, 54])

    def counts(_w):
        try:
            return next(seq)
        except StopIteration:
            return 54

    _patch(monkeypatch, count=counts, status="")
    assert _check_game_status(MagicMock(), timeout=3.0, settle=0.15) == (
        None,
        54,
    )
