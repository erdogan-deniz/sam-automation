"""Тесты manager_window — _click_refresh и retry/Refresh-логика process_game.

Фейки — plain-классы БЕЗ лишних атрибутов (не MagicMock): у живого UIAWrapper
нет child_window/wait, и вызов несуществующего метода должен ронять тест,
а не молча проходить (этот класс багов повторялся дважды).
"""

from __future__ import annotations

import pytest

import app.sam.manager_window as mw
from app.exceptions import SAMGameError
from app.sam.manager_window import _click_refresh, process_game


class _Rect:
    left, top, right, bottom = 0, 0, 800, 600


class _Btn:
    """Фейковая кнопка: только методы, существующие у UIAWrapper."""

    def __init__(self, cls: str, text: str):
        self._cls = cls
        self._text = text
        self.clicks = 0

    def friendly_class_name(self):
        return self._cls

    def window_text(self):
        return self._text

    def click_input(self):
        self.clicks += 1


class _Toolbar:
    def __init__(self, aid: str, *buttons: _Btn):
        self._aid = aid
        self._kids = list(buttons)

    def automation_id(self):
        return self._aid

    def children(self):
        return self._kids


class _Window:
    def __init__(self, *top_level, aid: str = "", title: str = ""):
        self._kids = list(top_level)
        self._aid = aid
        self._title = title

    def automation_id(self):
        return self._aid

    def window_text(self):
        return self._title

    def children(self):
        return self._kids

    def rectangle(self):
        return _Rect()


class _BrokenWindow:
    """Окно, у которого ВСЕ UIA-вызовы бросают (как зависшее)."""

    def automation_id(self):
        raise RuntimeError("UIA сломан")

    def window_text(self):
        raise RuntimeError("UIA сломан")

    def children(self):
        raise RuntimeError("UIA сломан")


class _App:
    def __init__(self, *windows):
        self._wins = list(windows)

    def windows(self):
        return list(self._wins)


def _manager_window(*extra):
    """Окно Manager: automation_id == 'Manager' (дешёвый маркер выбора)."""
    return _Window(*extra, aid="Manager")


# ── _find_manager_window ─────────────────────────────────────────────────────


def test_find_manager_window_picks_by_automation_id():
    transient = _Window(aid="SplashForm")  # не Manager
    manager = _manager_window()
    assert mw._find_manager_window(_App(transient, manager)) is manager


def test_find_manager_window_picks_by_title_fallback():
    # auto_id пуст, но в заголовке есть 'Steam Achievement Manager'
    win = _Window(aid="", title="Steam Achievement Manager 7.0 | Some Game")
    assert mw._find_manager_window(_App(_Window(aid="x"), win)) is win


def test_find_manager_window_none_when_no_manager():
    assert mw._find_manager_window(_App(_Window(aid="Other"))) is None


def test_find_manager_window_skips_broken_windows():
    # Зависшее окно (всё бросает) пропускается, настоящий Manager находится
    manager = _manager_window()
    assert mw._find_manager_window(_App(_BrokenWindow(), manager)) is manager


def test_find_manager_window_survives_windows_error():
    class _BadApp:
        def windows(self):
            raise RuntimeError("UIA busy")

    assert mw._find_manager_window(_BadApp()) is None


# ── _click_refresh ──────────────────────────────────────────────────────────


def test_click_refresh_finds_and_clicks_refresh_button():
    btn = _Btn("Button", "Refresh")
    toolbar = _Toolbar("_MainToolStrip", _Btn("Button", "Reset"), btn)
    win = _Window(_Toolbar("_OtherStrip"), toolbar)

    assert _click_refresh(win) is True
    assert btn.clicks == 1


def test_click_refresh_false_when_toolbar_has_no_refresh():
    toolbar = _Toolbar("_MainToolStrip", _Btn("Button", "Reset"))
    assert _click_refresh(_Window(toolbar)) is False


def test_click_refresh_false_when_no_main_toolstrip():
    assert _click_refresh(_Window(_Toolbar("_OtherStrip"))) is False


def test_click_refresh_false_on_exception():
    assert _click_refresh(_BrokenWindow()) is False


# ── process_game: retry/Refresh-логика ──────────────────────────────────────


def _run(monkeypatch, *, statuses, click_results, load_timeout=20):
    """Прогоняет process_game с фейками; возвращает (result, timeouts, clicks)."""
    app = _App(_manager_window())
    timeouts: list[float] = []
    seq = iter(statuses)

    def fake_check(_win, timeout):
        timeouts.append(timeout)
        return next(seq)

    clicks = {"n": 0}
    click_seq = iter(click_results)

    def fake_click(_w):
        clicks["n"] += 1
        return next(click_seq, False)

    monkeypatch.setattr(mw, "_check_game_status", fake_check)
    monkeypatch.setattr(mw, "_click_refresh", fake_click)
    monkeypatch.setattr(mw.time, "sleep", lambda _s: None)

    result = process_game(app, 123, load_timeout=load_timeout)
    return result, timeouts, clicks["n"]


def test_process_game_no_manager_window_raises(monkeypatch):
    # Ни одно окно не содержит _MainTabControl → SAMGameError (retryable),
    # детект даже не вызывается (раньше брали windows()[0] вслепую).
    app = _App(_Window(aid="SplashForm"))
    monkeypatch.setattr(mw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        mw, "_WINDOW_WAIT_FLOOR", 0.2
    )  # без 15с-ожидания в тесте
    monkeypatch.setattr(
        mw,
        "_check_game_status",
        lambda *a, **k: pytest.fail("детект не должен вызываться"),
    )
    with pytest.raises(SAMGameError):
        process_game(app, 123, load_timeout=0.2)


def test_refresh_recheck_uses_full_load_timeout(monkeypatch):
    # Refresh перезапускает загрузку с нуля → перепроверка должна ждать
    # столько же, сколько первая попытка (max(load_timeout, минимум))
    result, timeouts, _ = _run(
        monkeypatch,
        statuses=[("retry", 0), ("retry", 0)],
        click_results=[True],
        load_timeout=20,
    )
    assert result.skipped and result.skip_reason == "error"
    assert timeouts == [20, 20]


def test_refresh_recheck_floor_for_small_load_timeout(monkeypatch):
    # При маленьком load_timeout перепроверка не короче минимума
    _, timeouts, _ = _run(
        monkeypatch,
        statuses=[("retry", 0), ("retry", 0)],
        click_results=[True],
        load_timeout=3,
    )
    assert timeouts == [3, mw._REFRESH_RECHECK_TIMEOUT]


def test_failed_refresh_click_still_rechecks(monkeypatch):
    # Refresh не нажался (UIA-сбой) → клик повторяется, перепроверка ВСЁ РАВНО
    # выполняется: первая загрузка могла дозавершиться сама.
    result, timeouts, clicks = _run(
        monkeypatch,
        statuses=[("retry", 0), ("retry", 0)],
        click_results=[False, False],
    )
    assert clicks == 2  # повторный клик после неудачи
    assert (
        len(timeouts) == 2
    )  # перепроверка состоялась несмотря на провал клика
    assert result.skipped and result.skip_reason == "error"


def test_error_status_gets_refresh_chance_then_error(monkeypatch):
    # 'error' от SAM (транзиент?) → Refresh-шанс; снова error → error
    # (farm положит в error.txt — retryable), НЕ "no achievements".
    result, timeouts, clicks = _run(
        monkeypatch,
        statuses=[("error", 0), ("error", 0)],
        click_results=[True],
    )
    assert clicks == 1
    assert len(timeouts) == 2
    assert result.skipped and result.skip_reason == "error"


def test_error_status_recovers_after_refresh(monkeypatch):
    # 'error' был транзиентом: после Refresh статистика загрузилась
    cache = mw._ButtonCache()
    cache.unlock_all_dx = cache.unlock_all_dy = 10
    cache.commit_dx = cache.commit_dy = 20
    cache._calibrated = True
    monkeypatch.setattr(mw, "_cache", cache)
    monkeypatch.setattr(mw.mouse, "click", lambda coords: None)
    monkeypatch.setattr(mw.keyboard, "send_keys", lambda _k: None)

    result, _, _ = _run(
        monkeypatch,
        statuses=[("error", 0), (None, 54)],
        click_results=[True],
    )
    assert not result.skipped
    assert result.newly_unlocked == 54
