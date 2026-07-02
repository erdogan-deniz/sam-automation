"""Тесты _boost_loop: классификация survivors/failed, Ctrl+C, мульти-батч."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

_BOOST_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "playtime" / "boost.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "boost_under_test", _BOOST_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boost = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "playtime_concurrent_games": 10,
        "playtime_idle_duration": 1,
        "launch_stagger": 0.0,
        "sam_game_exe_path": "x",
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_boost_loop_marks_done_skip_and_spares_known(monkeypatch):
    done: list[int] = []
    skip: list[int] = []
    seen: dict[str, object] = {}
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", skip.append)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    # Стаб как реальная функция: 10/20 выжили, 30 провалился (через on_failed).
    def fake_idle(active, idle, on_failed=None):
        seen["idle"] = idle
        if on_failed is not None:
            on_failed(30)
        return ([10, 20], [30])

    monkeypatch.setattr(boost, "idle_and_split_survivors", fake_idle)

    games = [
        {"appid": 10, "name": "A", "playtime_forever": 0, "known": True},
        {"appid": 20, "name": "B", "playtime_forever": 0, "known": False},
        {"appid": 30, "name": "C", "playtime_forever": 0, "known": False},
    ]
    boost._boost_loop(games, _cfg(playtime_idle_duration=7))

    # unknown-выживший → done; known-выживший НЕ пишем; провал → skip (on_failed)
    assert done == [20]
    assert skip == [30]
    # idle_duration проброшен в функцию
    assert seen["idle"] == 7


def test_boost_loop_ctrl_c_kills_active_without_marking_done(monkeypatch):
    # Инвариант: Ctrl+C убивает активные, но НЕ пишет done.
    done: list[int] = []
    killed: list[object] = []
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", killed.append)
    # Замокать, иначе тест зовёт настоящий win32 TerminateProcess по всем
    # SAM.Game.exe — убьёт активный boost/farm, если он идёт во время pytest.
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def boom(active, idle, on_failed=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(boost, "idle_and_split_survivors", boom)

    games = [
        {"appid": 10, "name": "A", "playtime_forever": 0, "known": False},
        {"appid": 20, "name": "B", "playtime_forever": 0, "known": False},
    ]
    boost._boost_loop(games, _cfg())  # не должно пробросить наружу

    assert done == []  # ничего не помечено done
    assert len(killed) == 2  # все активные убиты


def test_boost_loop_ctrl_c_after_failure_keeps_skip(monkeypatch):
    # Провал задетектирован и записан в skip во время idle, ЗАТЕМ Ctrl+C →
    # skip сохранён (on_failed пишет в момент детекции, не после возврата).
    skip: list[int] = []
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", skip.append)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def fail_then_interrupt(active, idle, on_failed=None):
        on_failed(30)  # провал зафиксирован в skip
        raise KeyboardInterrupt  # затем прерывание

    monkeypatch.setattr(boost, "idle_and_split_survivors", fail_then_interrupt)

    games = [{"appid": 30, "name": "C", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())

    assert skip == [30]  # skip пережил Ctrl+C


def test_boost_loop_ctrl_c_during_launch_kills_all_sam(monkeypatch):
    # Ctrl+C во время staggered-запуска батча: процессы уже стартовали, но ещё
    # не в active → обычный проход их не тронет. Страховка kill_all_sam_games
    # добивает все SAM.Game.exe, чтобы не осиротить.
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    swept: list[bool] = []
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: swept.append(True))

    def launch_interrupts(exe, games, stagger):
        raise KeyboardInterrupt  # прерывание во время запуска батча

    monkeypatch.setattr(boost, "launch_games_staggered", launch_interrupts)

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())  # не должно пробросить наружу

    assert swept == [True]  # страховка добила процессы


def test_boost_loop_multi_batch_pauses_between_not_after(monkeypatch):
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    sleeps: list[float] = []
    monkeypatch.setattr(boost.time, "sleep", sleeps.append)
    launched: list[list[int]] = []

    def fake_launch(exe, games, stagger):
        launched.append([appid for appid, _ in games])
        return {appid: object() for appid, _ in games}

    monkeypatch.setattr(boost, "launch_games_staggered", fake_launch)
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: (list(active.keys()), []),
    )

    games = [
        {"appid": i, "name": str(i), "playtime_forever": 0, "known": False}
        for i in (10, 20, 30)
    ]
    boost._boost_loop(games, _cfg(playtime_concurrent_games=2))

    # 3 игры по 2 → два батча: [10, 20] и [30]
    assert launched == [[10, 20], [30]]
    # _PAUSE_AFTER_KILL ровно один раз — между батчами, не после последнего
    assert sleeps == [boost._PAUSE_AFTER_KILL]
