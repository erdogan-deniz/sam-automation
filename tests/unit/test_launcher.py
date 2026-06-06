"""Тесты launch_games_staggered — пауза между стартами SAM.Game.exe.

Гонка за Steam global user возникает при одновременном старте нескольких
SAM.Game.exe ('failed to connect to global user'). Пауза МЕЖДУ запусками
её устраняет.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import app.sam.launcher as launcher
from app.sam.launcher import (
    _LAUNCH_STAGGER,
    drop_failed_launches,
    launch_games_staggered,
)


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


def test_drop_failed_removes_and_kills_error_processes(monkeypatch):
    p1, p2, p3 = MagicMock(pid=1), MagicMock(pid=2), MagicMock(pid=3)
    active = {10: p1, 20: p2, 30: p3}
    killed: list = []
    # Окно 'Error' только у процесса с pid=2 (appid 20)
    monkeypatch.setattr(launcher, "_has_error_window", lambda pid: pid == 2)
    monkeypatch.setattr(launcher, "kill_process", killed.append)
    monkeypatch.setattr(launcher.time, "sleep", lambda _s: None)

    failed = drop_failed_launches(active, check_delay=0)

    assert failed == [20]
    assert set(active) == {10, 30}  # провалившийся удалён из active
    assert killed == [p2]  # и убит


def test_drop_failed_empty_active_returns_empty():
    assert drop_failed_launches({}) == []
