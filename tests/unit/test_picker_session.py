"""Тесты PickerSession — money-path: ID → Add → двойной клик → ждём SAM.Game.

Закрывают пробел покрытия на критичном пути: каждый исход add_and_open_game
должен либо вернуть подключённое приложение, либо бросить SAMGameError (игра
уходит в error.txt — retryable), НИКОГДА не отдавая «успех» без процесса/окна
и не оставляя запущенный SAM.Game сиротой.

Фейки — plain-классы. ВАЖНО: здесь child_window/wait у фейка ЛЕГИТИМНЫ —
PickerSession берёт окно через app.window(auto_id=...), т.е. WindowSpecification
(у него эти методы есть), в отличие от UIAWrapper из app.windows()[0].
"""

from __future__ import annotations

import pytest

import app.sam.picker_session as ps
from app.exceptions import SAMGameError
from app.sam.picker_session import PickerSession

_PICKER_HWND = 4242
_PICKER_PID = 111


class _Clock:
    """Фейковые часы: sleep двигает время — дедлайны истекают детерминированно."""

    def __init__(self) -> None:
        self.t = 1000.0

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s or 0.05


class _Rect:
    left, top, right, bottom = 0, 0, 100, 40


class _Item:
    def friendly_class_name(self) -> str:
        return "ListItem"

    def rectangle(self) -> _Rect:
        return _Rect()


class _Edit:
    def __init__(self) -> None:
        self.text: str | None = None

    def friendly_class_name(self) -> str:
        return "Edit"

    def set_edit_text(self, t: str) -> None:
        self.text = t


class _AddBtn:
    def __init__(self) -> None:
        self.clicks = 0

    def friendly_class_name(self) -> str:
        return "Button"

    def window_text(self) -> str:
        return "Add Game"

    def click_input(self) -> None:
        self.clicks += 1


class _Toolbar:
    def __init__(self, kids: list) -> None:
        self._kids = kids

    def children(self) -> list:
        return self._kids


class _ListView:
    def __init__(self, items: list) -> None:
        self._items = items

    def children(self) -> list:
        return self._items


class _Wrapper:
    handle = _PICKER_HWND


class _PickerWin:
    """Фейк WindowSpecification (child_window/wait существуют у реального типа)."""

    def __init__(self, toolbar: _Toolbar, listview: _ListView) -> None:
        self._toolbar = toolbar
        self._listview = listview

    def wait(self, *a, **k) -> _PickerWin:
        return self

    def process_id(self) -> int:
        return _PICKER_PID

    def child_window(self, auto_id: str | None = None, **k):
        if auto_id == "_PickerToolStrip":
            return self._toolbar
        if auto_id == "_GameListView":
            return self._listview
        raise AssertionError(f"неожиданный auto_id: {auto_id}")

    def set_focus(self) -> None:
        return None

    def wrapper_object(self) -> _Wrapper:
        return _Wrapper()


class _PickerApp:
    def __init__(self, win: _PickerWin) -> None:
        self._win = win

    def window(self, auto_id: str | None = None, **k) -> _PickerWin:
        assert auto_id == "GamePicker"
        return self._win


class _GameApp:
    """Подключённое приложение SAM.Game: windows() отдаёт окна (или пусто)."""

    def __init__(self, windows: list) -> None:
        self._windows = windows

    def windows(self) -> list:
        return self._windows


def _session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    items: list | None = None,
    with_controls: bool = True,
) -> PickerSession:
    clock = _Clock()
    monkeypatch.setattr(ps.time, "time", clock.time)
    monkeypatch.setattr(ps.time, "sleep", clock.sleep)
    monkeypatch.setattr(ps.mouse, "double_click", lambda coords: None)
    kids: list = [_Edit(), _AddBtn()] if with_controls else []
    win = _PickerWin(_Toolbar(kids), _ListView(items if items else []))
    return PickerSession(_PickerApp(win))


def test_missing_picker_controls_raises(monkeypatch):
    # Нет Edit/Add в тулбаре → игра не добавляется, честная ошибка.
    session = _session(monkeypatch, with_controls=False)
    with pytest.raises(SAMGameError, match="Элементы Picker не найдены"):
        session.add_and_open_game(730)


def test_modal_dialog_means_sam_rejected_game(monkeypatch):
    # Picker стал disabled → modal («You don't own the game»): SAM отверг игру.
    # Список может содержать ПРЕДЫДУЩУЮ игру — успех отдавать нельзя.
    session = _session(monkeypatch, items=[_Item()])
    monkeypatch.setattr(ps, "_is_window_enabled", lambda _h: False)
    monkeypatch.setattr(ps, "_close_picker_modal", lambda _h, _p: True)
    with pytest.raises(SAMGameError, match="ошибка добавления игры"):
        session.add_and_open_game(730)


def test_no_items_and_no_dialog_means_game_unavailable(monkeypatch):
    # Ни игры в списке, ни диалога → игра просто недоступна (retryable error).
    session = _session(monkeypatch, items=[])
    monkeypatch.setattr(ps, "_is_window_enabled", lambda _h: True)
    with pytest.raises(SAMGameError, match="игра недоступна"):
        session.add_and_open_game(730)


def test_no_new_pid_raises(monkeypatch):
    # Двойной клик не породил SAM.Game → честная ошибка, не «успех».
    session = _session(monkeypatch, items=[_Item()])
    monkeypatch.setattr(ps, "_is_window_enabled", lambda _h: True)
    monkeypatch.setattr(ps, "_get_sam_game_pids", lambda: {1, 2})  # без новых
    with pytest.raises(SAMGameError, match="не появился"):
        session.add_and_open_game(730, timeout=0.2)


def test_window_never_appears_kills_spawned_pid(monkeypatch):
    # Процесс поднялся, но окно Manager не пришло → убиваем СВОЙ SAM.Game,
    # иначе он остаётся сиротой и дерётся за Steam global user.
    session = _session(monkeypatch, items=[_Item()])
    monkeypatch.setattr(ps, "_is_window_enabled", lambda _h: True)
    pids = iter([{1}, {1, 999}])
    monkeypatch.setattr(ps, "_get_sam_game_pids", lambda: next(pids, {1, 999}))
    killed: list[int] = []
    monkeypatch.setattr(ps, "_kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr(
        ps,
        "Application",
        lambda backend: type(
            "_C", (), {"connect": lambda _s, **k: _GameApp([])}
        )(),
    )
    with pytest.raises(SAMGameError, match="Окно Manager не появилось"):
        session.add_and_open_game(730, timeout=0.2)
    assert killed == [999]  # сирота не оставлен


def test_success_returns_connected_game_app(monkeypatch):
    session = _session(monkeypatch, items=[_Item()])
    monkeypatch.setattr(ps, "_is_window_enabled", lambda _h: True)
    pids = iter([{1}, {1, 999}])
    monkeypatch.setattr(ps, "_get_sam_game_pids", lambda: next(pids, {1, 999}))
    killed: list[int] = []
    monkeypatch.setattr(ps, "_kill_pid", lambda pid: killed.append(pid))
    game_app = _GameApp(["manager-window"])
    monkeypatch.setattr(
        ps,
        "Application",
        lambda backend: type("_C", (), {"connect": lambda _s, **k: game_app})(),
    )
    assert session.add_and_open_game(730, timeout=1.0) is game_app
    assert killed == []  # успешный процесс не убиваем
