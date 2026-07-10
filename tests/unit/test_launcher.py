"""Тесты launch_games_staggered и idle_and_split_survivors.

Гонка за Steam global user возникает при одновременном старте нескольких
SAM.Game.exe ('failed to connect to global user'). Пауза МЕЖДУ запусками
её устраняет.

Провал подключения — сигнал НЕ «есть окно ошибки в один момент» (оно
транзиентное: процесс показывает 'Error' и сам умирает за секунды), а
«процесс не пережил весь idle». idle_and_split_survivors отбирает выживших.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import app.sam.launcher as launcher
from app.sam.launcher import (
    _LAUNCH_STAGGER,
    idle_and_split_survivors,
    launch_games_staggered,
)


class _FakeProc:
    """Фейк subprocess.Popen с управляемым poll().

    poll_value — фиксированный результат (None=жив, int=мёртв).
    dies_after — жив первые N опросов, затем мёртв (имитация смерти в idle).
    """

    def __init__(
        self,
        pid: int,
        poll_value: int | None = None,
        dies_after: int | None = None,
    ) -> None:
        self.pid = pid
        self._poll_value = poll_value
        self._dies_after = dies_after
        self._polls = 0

    def poll(self) -> int | None:
        self._polls += 1
        if self._dies_after is not None:
            return None if self._polls <= self._dies_after else 1
        return self._poll_value


class _Clock:
    """Фейковые time.time/time.sleep: sleep двигает часы, чтобы цикл сходился."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def test_staggered_launch_pauses_between_but_not_before_first():
    games = [(1, "A"), (2, "B"), (3, "C")]
    with (
        patch("app.sam.launcher.launch_game") as mock_launch,
        patch("app.sam.launcher.time.sleep") as mock_sleep,
    ):
        mock_launch.side_effect = lambda exe, appid: MagicMock(name=f"p{appid}")
        active = launch_games_staggered("sam.exe", games, stagger=2.0)

    # Все три игры запущены
    assert mock_launch.call_count == 3
    assert list(active.keys()) == [1, 2, 3]
    # 3 игры → 2 паузы (между запусками), перед первой паузы нет
    assert mock_sleep.call_args_list == [call(2.0), call(2.0)]


def test_staggered_launch_single_game_has_no_pause():
    with (
        patch("app.sam.launcher.launch_game") as mock_launch,
        patch("app.sam.launcher.time.sleep") as mock_sleep,
    ):
        mock_launch.return_value = MagicMock()
        launch_games_staggered("sam.exe", [(42, "Solo")])

    assert mock_launch.call_count == 1
    mock_sleep.assert_not_called()  # один запуск — гонки нет, паузы нет


def test_staggered_launch_uses_default_stagger():
    games = [(1, "A"), (2, "B")]
    with (
        patch("app.sam.launcher.launch_game") as mock_launch,
        patch("app.sam.launcher.time.sleep") as mock_sleep,
    ):
        mock_launch.return_value = MagicMock()
        launch_games_staggered("sam.exe", games)

    mock_sleep.assert_called_once_with(_LAUNCH_STAGGER)


def test_staggered_launch_empty_list_returns_empty():
    with patch("app.sam.launcher.launch_game") as mock_launch:
        active = launch_games_staggered("sam.exe", [])
    assert active == {}
    mock_launch.assert_not_called()


def _patch_clock_and_kill(monkeypatch) -> tuple[_Clock, list]:
    clock = _Clock()
    killed: list = []
    monkeypatch.setattr(launcher.time, "time", clock.time)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    monkeypatch.setattr(launcher, "kill_process", killed.append)
    return clock, killed


def test_idle_split_all_survive_marks_survivors_and_idles_full(monkeypatch):
    clock, killed = _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    p1, p2 = _FakeProc(1), _FakeProc(2)  # оба живы (poll=None), без ошибки
    active = {10: p1, 20: p2}

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=10, poll_interval=5
    )

    assert sorted(survivors) == [10, 20]
    assert failed == []
    assert set(killed) == {p1, p2}  # выживших убиваем в конце
    assert sum(clock.sleeps) == 10  # идлили весь срок


def test_idle_split_dead_or_error_go_to_failed(monkeypatch):
    clock, killed = _patch_clock_and_kill(monkeypatch)
    # Окно 'Error' у живого процесса с pid=3 (appid 30)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: pid == 3)
    p_ok = _FakeProc(1, None)  # жив, без ошибки → survivor
    p_dead = _FakeProc(2, 1)  # завершился сам → failed
    p_err = _FakeProc(3, None)  # жив, но окно ошибки → failed
    active = {10: p_ok, 20: p_dead, 30: p_err}

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=10, poll_interval=5
    )

    assert survivors == [10]
    assert sorted(failed) == [20, 30]
    assert set(killed) == {p_ok, p_dead, p_err}  # убиты все


def test_idle_split_exits_early_when_all_fail(monkeypatch):
    clock, killed = _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    p1, p2 = _FakeProc(1, 1), _FakeProc(2, 1)  # оба мертвы
    active = {10: p1, 20: p2}

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=120, poll_interval=5
    )

    assert survivors == []
    assert sorted(failed) == [10, 20]
    # Все провалились на первой проверке → не идлим все 120с
    assert sum(clock.sleeps) == 5


def test_idle_split_empty_active_returns_empty(monkeypatch):
    _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    survivors, failed = idle_and_split_survivors({}, idle_duration=10)
    assert survivors == []
    assert failed == []


def test_idle_split_process_dies_mid_idle_is_failed(monkeypatch):
    # Суть фикса: игра жива на первом опросе, умирает позже (окно 'Error'
    # транзиентное). Единственная ранняя проверка её бы пропустила.
    _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    p = _FakeProc(1, dies_after=1)  # жив на 1-м опросе, мёртв на 2-м
    active = {10: p}

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=10, poll_interval=5
    )

    assert survivors == []
    assert failed == [10]


def test_idle_split_error_window_appears_mid_idle_is_failed(monkeypatch):
    # Окно 'Error' появляется не сразу, а на втором опросе (транзиентное).
    _patch_clock_and_kill(monkeypatch)
    calls = {"n": 0}

    def _err(pid: int) -> bool:
        calls["n"] += 1
        return calls["n"] >= 2  # на 1-м опросе ошибки нет, на 2-м — есть

    monkeypatch.setattr(launcher, "_has_error_window", _err)
    active = {10: _FakeProc(1, None)}  # процесс жив весь idle

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=10, poll_interval=5
    )

    assert survivors == []
    assert failed == [10]


def test_idle_split_calls_on_failed_at_detection(monkeypatch):
    # on_failed вызывается в МОМЕНТ детекции (skip пишется до конца idle —
    # переживает Ctrl+C во время idle).
    _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    skipped: list[int] = []
    active = {20: _FakeProc(2, 1), 10: _FakeProc(1, None)}

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=10, poll_interval=5, on_failed=skipped.append
    )

    assert skipped == [20]
    assert failed == [20]
    assert survivors == [10]


def test_idle_split_zero_idle_still_checks_each_process(monkeypatch):
    # idle_duration=0 не должен слепо признавать всех выжившими.
    _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    active = {20: _FakeProc(2, 1)}  # уже мёртв

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=0, poll_interval=5
    )

    assert survivors == []
    assert failed == [20]


def test_idle_split_zero_poll_interval_terminates(monkeypatch):
    # poll_interval<=0 не должен зацикливаться: кламп до 0.1 двигает часы к deadline.
    clock, _ = _patch_clock_and_kill(monkeypatch)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: False)
    active = {10: _FakeProc(1, None)}  # процесс жив весь idle

    survivors, failed = idle_and_split_survivors(
        active, idle_duration=1, poll_interval=0
    )

    assert survivors == [10]
    assert failed == []
    # кламп сработал: ни одного sleep(0) (иначе часы бы не двигались → вечный
    # цикл) и цикл сошёлся за конечное число шагов
    assert clock.sleeps and all(s > 0 for s in clock.sleeps)
    assert len(clock.sleeps) < 100
