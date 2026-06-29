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


# ── _read_achievement_count: фейковое UIA-дерево ───────────────────────────
#
# Важно: как и живой UIAWrapper (app.windows()[0]), фейк НЕ имеет метода
# child_window — он есть только у WindowSpecification. Реализация обязана
# обходить дерево через children().


class _Ctrl:
    """Фейковый UIA-контрол: children()/automation_id()/friendly_class_name()."""

    def __init__(self, cls="", aid="", kids=None, text=""):
        self._cls = cls
        self._aid = aid
        self._kids = kids or []
        self._text = text

    def automation_id(self):
        return self._aid

    def friendly_class_name(self):
        return self._cls

    def children(self):
        return self._kids

    def window_text(self):
        return self._text


def _fake_window(n_items: int) -> _Ctrl:
    """Дерево как в реальном дампе SAM.Game (Manager)."""
    items = [_Ctrl("ListItem") for _ in range(n_items)]
    listview = _Ctrl(
        "ListBox",
        "_AchievementListView",
        [_Ctrl("Header"), _Ctrl("ScrollBar")] + items,
    )
    tab = _Ctrl(
        "TabControl",
        "_MainTabControl",
        [_Ctrl("Pane", "_AchievementsTabPage", [listview])],
    )
    return _Ctrl(
        "Dialog",
        "Manager",
        [_Ctrl("Toolbar", "_MainToolStrip"), tab, _Ctrl("StatusBar")],
    )


def test_read_count_walks_children_of_real_layout():
    # 54 ListItem + Header/ScrollBar в списке → ровно 54
    assert ss._read_achievement_count(_fake_window(54)) == 54


def test_read_count_empty_list_is_zero():
    assert ss._read_achievement_count(_fake_window(0)) == 0


def test_read_count_no_list_control_is_none():
    # Окно без _AchievementListView (ещё грузится) → None
    win = _Ctrl("Dialog", "Manager", [_Ctrl("Toolbar", "_MainToolStrip")])
    assert ss._read_achievement_count(win) is None


def test_read_count_survives_broken_controls():
    # Контрол, кидающий исключение, пропускается, список всё равно находится
    class _Broken:
        def automation_id(self):
            raise RuntimeError("COM error")

        def friendly_class_name(self):
            raise RuntimeError("COM error")

        def children(self):
            raise RuntimeError("COM error")

    win = _fake_window(7)
    win._kids.insert(0, _Broken())
    assert ss._read_achievement_count(win) == 7


# ── _read_status_panel: прямые тесты (НЕ мокаем саму функцию) ──────────────


def test_read_status_text_on_bar_lowercased():
    win = _Ctrl(
        "Dialog",
        kids=[_Ctrl("StatusBar", text="Retrieved 54 achievements.")],
    )
    assert ss._read_status_panel(win) == "retrieved 54 achievements."


def test_read_status_text_in_child_panel():
    # Текст не на самом баре, а в дочерней панели (как в реальном дампе)
    bar = _Ctrl(
        "StatusBar",
        kids=[
            _Ctrl("Static", text=""),
            _Ctrl("Static", text="Retrieved 0 achievements and 5 statistics."),
        ],
    )
    win = _Ctrl("Dialog", kids=[_Ctrl("Toolbar", "_MainToolStrip"), bar])
    assert (
        ss._read_status_panel(win)
        == "retrieved 0 achievements and 5 statistics."
    )


def test_read_status_no_statusbar_is_empty():
    win = _Ctrl("Dialog", kids=[_Ctrl("Toolbar", "_MainToolStrip")])
    assert ss._read_status_panel(win) == ""


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


def test_status_error_returns_error_reason(monkeypatch):
    # 'error' в статус-баре часто транзиентен (Steam/сеть) → отдельная причина
    # "error": caller даст Refresh-шанс, финально игра уйдёт в error.txt
    # (retryable через --retry-errors), а НЕ в without.txt навсегда.
    _patch(monkeypatch, count=0, status="error: failed to retrieve")
    assert _check_game_status(MagicMock(), timeout=2.0, settle=0.1) == (
        "error",
        0,
    )


def test_unstable_count_at_deadline_returns_count(monkeypatch):
    # Список есть, но не успел стабилизироваться к дедлайну → берём как есть
    # (Unlock All работает по фактически загруженному списку), а не retry.
    state = {"n": 0}

    def growing(_w):
        state["n"] += 1
        return state["n"]

    _patch(monkeypatch, count=growing, status="")
    reason, count = _check_game_status(MagicMock(), timeout=0.5, settle=99.0)
    assert reason is None
    assert count > 0


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
